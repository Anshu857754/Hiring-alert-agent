"""Demo account me showcase data bharo — ek asli run ki copy.

    python seed_demo.py anshu.singh8595508@gmail.com

Kis account se copy karna hai wo argument me do. Demo account (config.DEMO_EMAIL)
na ho to ban jaata hai. Har baar chalane par demo ka purana data hata kar
naya bharta hai, isliye baar-baar chalana safe hai.

Sender account **copy nahi hota** — usme sealed LinkedIn cookie hoti hai, aur
public demo me uska koi kaam nahi.
"""
import asyncio
import sys

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

load_dotenv(".env")

from app import config, db, users  # noqa: E402
from app.db import S  # noqa: E402

# jobs `searches` ke through aate hain, isliye alag se handle hote hain.
COPY_TABLES = ["searches", "plans", "outreach", "contacts"]


def adapt(value):
    """JSONB column padhne par dict/list milta hai; wapas daalne ke liye
    psycopg ko Jsonb() chahiye, warna "cannot adapt type 'dict'"."""
    return Jsonb(value) if isinstance(value, (dict, list)) else value


async def _columns(table: str) -> list[str]:
    rows = await db.fetch_all(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
         ORDER BY ordinal_position
        """,
        (config.DB_SCHEMA, table),
    )
    # id identity column hai — copy karte waqt naya banega.
    return [r["column_name"] for r in rows if r["column_name"] != "id"]


async def _wipe_demo(demo_id: int) -> None:
    # jobs searches ke ON DELETE CASCADE se apne aap jaate hain.
    for table in ["outreach", "contacts", "plans", "saved_jobs", "searches"]:
        gone = await db.execute(f"DELETE FROM {S}{table} WHERE user_id = %s", (demo_id,))
        if gone:
            print(f"  purana {table:10s} hataya: {gone}")


async def main(source_email: str) -> int:
    db.connect_sync(migrate=False)
    if not db.enabled():
        print("DB connect nahi hui:", db.status())
        return 1

    src = await db.fetch_one(
        f"SELECT id, email FROM {S}users WHERE lower(email) = %s", (source_email.strip().lower(),)
    )
    if not src:
        print(f"Source account nahi mila: {source_email}")
        return 1

    demo = await users.ensure_demo_user()
    if not demo:
        print("Demo account nahi bana — DEMO_ENABLED check karo")
        return 1
    if demo["id"] == src["id"]:
        print("Source aur demo ek hi account hai — kuch karne ka matlab nahi")
        return 1

    print(f'\nSource : {src["email"]} (id {src["id"]})')
    print(f'Demo   : {demo["email"]} (id {demo["id"]})\n')

    await _wipe_demo(demo["id"])

    search_id_map: dict[int, int] = {}

    # ── searches + unke jobs ──
    cols = await _columns("searches")
    assign = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    rows = await db.fetch_all(f"SELECT * FROM {S}searches WHERE user_id = %s ORDER BY id", (src["id"],))
    for row in rows:
        values = [demo["id"] if c == "user_id" else adapt(row[c]) for c in cols]
        new = await db.fetch_one(
            f"INSERT INTO {S}searches ({assign}) VALUES ({placeholders}) RETURNING id", values
        )
        search_id_map[row["id"]] = new["id"]
    print(f"  searches   copied: {len(rows)}")

    job_cols = await _columns("jobs")
    j_assign = ", ".join(f'"{c}"' for c in job_cols)
    j_placeholders = ", ".join(["%s"] * len(job_cols))
    total_jobs = 0
    for old_sid, new_sid in search_id_map.items():
        jobs = await db.fetch_all(
            f"SELECT * FROM {S}jobs WHERE search_id = %s ORDER BY position", (old_sid,)
        )
        for job in jobs:
            values = [new_sid if c == "search_id" else adapt(job[c]) for c in job_cols]
            await db.execute(f"INSERT INTO {S}jobs ({j_assign}) VALUES ({j_placeholders})", values)
        total_jobs += len(jobs)
    print(f"  jobs       copied: {total_jobs}")

    # ── baaki tables ──
    for table in COPY_TABLES[1:]:
        cols = await _columns(table)
        assign = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(["%s"] * len(cols))
        rows = await db.fetch_all(f"SELECT * FROM {S}{table} WHERE user_id = %s ORDER BY id", (src["id"],))
        for row in rows:
            values = []
            for c in cols:
                if c == "user_id":
                    values.append(demo["id"])
                elif c == "search_id":
                    # Purana search_id demo ke naye id par map karo, warna
                    # foreign key kisi aur user ki row par point karti.
                    values.append(search_id_map.get(row[c]))
                else:
                    values.append(adapt(row[c]))
            await db.execute(f"INSERT INTO {S}{table} ({assign}) VALUES ({placeholders})", values)
        print(f"  {table:10s} copied: {len(rows)}")

    await db.close()
    print("\nHo gaya. Login screen par 'Try the demo' se ye data dikhega.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
