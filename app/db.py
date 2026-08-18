"""Postgres (Neon) connection pool + migration runner.

psycopg ka **sync** pool use karte hain aur har query `asyncio.to_thread` me
chalti hai. Wajah: Windows par asyncio ka default ProactorEventLoop psycopg ke
async mode ko support nahi karta (uvicorn wahi loop banata hai), aur is app ka
DB load itna halka hai ki thread pool bilkul kaafi hai — waise bhi markitdown
pehle se isi tarike se chalta hai.

DATABASE_URL na ho to `enabled` False rehta hai: app poori tarah chalti hai,
bas kuch persist nahi hota. Ek bhi jagah crash nahi hona chahiye.
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

log = logging.getLogger("hiring-agent.db")

_pool: ConnectionPool | None = None
_last_error: str | None = None

# 0001_init.sql -> 1
_VERSION_RE = re.compile(r"^(\d+)")


def schema_prefix() -> str:
    """`"hiring_agent".` — har query me table ke aage lagta hai.

    search_path par bharosa nahi kiya ja sakta: Neon ka `-pooler` endpoint
    pgbouncer transaction mode me chalta hai, jahan har transaction alag server
    connection par ja sakti hai aur session ka `SET search_path` gayab ho jaata
    hai. Isliye table names hamesha schema ke saath likhe jaate hain.
    """
    return '"' + config.DB_SCHEMA.replace('"', '""') + '".'


# Import ke waqt hi ban jaata hai — queries isi ko prefix karti hain.
S = schema_prefix()


def enabled() -> bool:
    return _pool is not None


def status() -> dict:
    return {"configured": bool(config.DATABASE_URL), "connected": enabled(), "error": _last_error, "schema": config.DB_SCHEMA}


def _configure(conn) -> None:
    """Har pooled connection apne aap hamare schema me kaam kare."""
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(config.DB_SCHEMA)))
    conn.commit()


# ─────────────────────────── migrations ───────────────────────────

def _migration_files() -> list[Path]:
    if not config.MIGRATIONS_DIR.exists():
        return []
    return sorted(config.MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def _version_of(path: Path) -> int:
    m = _VERSION_RE.match(path.name)
    return int(m.group(1)) if m else 0


def _apply_migrations(pool: ConnectionPool) -> list[str]:
    """Pending .sql files ko order me chalata hai. Har file apne transaction me.

    Yaad rahe: ye database dusre project ke saath share hota hai (uska apna
    alembic_version public schema me pada hai). Isliye hum na uski table chhoote
    hain, na alembic use karte hain — apna chhota sa schema_migrations kaafi hai.
    """
    applied: list[str] = []
    schema = sql.Identifier(config.DB_SCHEMA)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Schema pehle banana zaroori hai — warna search_path fallback ho kar
            # tables galti se public me ban jaate.
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
            cur.execute(sql.SQL("SET search_path TO {}, public").format(schema))
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {S}schema_migrations (
                    version    INTEGER      PRIMARY KEY,
                    name       TEXT         NOT NULL,
                    applied_at TIMESTAMPTZ  NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(f"SELECT version FROM {S}schema_migrations")
            done = {row["version"] for row in cur.fetchall()}

    for path in _migration_files():
        version = _version_of(path)
        if version in done:
            continue
        body = path.read_text(encoding="utf-8")
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(schema))
                cur.execute(body)
                cur.execute(
                    f"INSERT INTO {S}schema_migrations (version, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (version, path.name),
                )
            conn.commit()
        applied.append(path.name)
        log.info("migration applied: %s", path.name)

    return applied


def pending_migrations() -> list[str]:
    """CLI ke liye — abhi kaunsi files baaki hain."""
    if _pool is None:
        return [p.name for p in _migration_files()]
    try:
        with _pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT version FROM {S}schema_migrations")
            done = {row["version"] for row in cur.fetchall()}
    except Exception:
        # Table hi nahi bani — matlab abhi kuch bhi apply nahi hua.
        done = set()
    return [p.name for p in _migration_files() if _version_of(p) not in done]


def drop_schema_sync() -> None:
    """Sirf `migrate.py --reset` ke liye — poora app schema gira deta hai."""
    assert _pool is not None
    with _pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(config.DB_SCHEMA)))
        conn.commit()


# ─────────────────────────── lifecycle ───────────────────────────

def connect_sync(*, migrate: bool = True) -> list[str]:
    """Pool kholta hai aur (default) pending migrations chala deta hai."""
    global _pool, _last_error

    if not config.DATABASE_URL:
        _last_error = "DATABASE_URL not set in .env"
        log.warning("DATABASE_URL missing — history/saved jobs will not persist")
        return []

    pool = ConnectionPool(
        conninfo=config.DATABASE_URL,
        min_size=config.DB_POOL_MIN,
        max_size=config.DB_POOL_MAX,
        configure=_configure,
        kwargs={"connect_timeout": 15, "application_name": "hiring-agent"},
        open=False,
    )
    try:
        pool.open(wait=True, timeout=30)
        applied = _apply_migrations(pool) if migrate else []
    except Exception as err:
        _last_error = str(err)
        log.error("database unavailable: %s", err)
        try:
            pool.close()
        except Exception:
            pass
        return []

    _pool = pool
    _last_error = None
    return applied


async def connect() -> list[str]:
    return await asyncio.to_thread(connect_sync)


def close_sync() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


async def close() -> None:
    await asyncio.to_thread(close_sync)


# ─────────────────────────── query helpers ───────────────────────────
# Sab kuch thread me chalta hai; DB down ho to fetch* khaali lautate hain
# taaki ek bhi request 500 par na gire.

def _fetch_all(query: str, args: Sequence[Any] = ()) -> list[dict]:
    assert _pool is not None
    with _pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, args)
        return list(cur.fetchall())


def _fetch_one(query: str, args: Sequence[Any] = ()) -> dict | None:
    assert _pool is not None
    with _pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchone()


def _execute(query: str, args: Sequence[Any] = ()) -> int:
    assert _pool is not None
    with _pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, args)
        return cur.rowcount


def _execute_many(query: str, rows: Iterable[Sequence[Any]]) -> None:
    assert _pool is not None
    rows = list(rows)
    if not rows:
        return
    with _pool.connection() as conn, conn.cursor() as cur:
        cur.executemany(query, rows)


async def fetch_all(query: str, args: Sequence[Any] = ()) -> list[dict]:
    if not enabled():
        return []
    return await asyncio.to_thread(_fetch_all, query, args)


async def fetch_one(query: str, args: Sequence[Any] = ()) -> dict | None:
    if not enabled():
        return None
    return await asyncio.to_thread(_fetch_one, query, args)


async def execute(query: str, args: Sequence[Any] = ()) -> int:
    if not enabled():
        return 0
    return await asyncio.to_thread(_execute, query, args)


async def execute_many(query: str, rows: Iterable[Sequence[Any]]) -> None:
    if not enabled():
        return
    await asyncio.to_thread(_execute_many, query, rows)
