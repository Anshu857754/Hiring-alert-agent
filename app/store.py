"""Saara DB kaam yahan — routes sirf in functions ko bulate hain.

Frontend camelCase bolta hai, Postgres snake_case. Badalne ka kaam bhi yahin
hota hai taaki main.py saaf rahe.
"""
import json
import re
from typing import Any

from . import config, db
from .db import S   # '"hiring_agent".' — har table ke aage


def job_key(job: dict) -> str:
    """Wahi key jo frontend bhi banata hai — url, warna source:title:company."""
    return job.get("url") or f"{job.get('source')}:{job.get('title')}:{job.get('company')}"


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _job_row(job: dict) -> dict:
    return {
        "job_key": job_key(job),
        "source": _text(job.get("source")),
        "title": _text(job.get("title")),
        "company": _text(job.get("company")),
        "location": _text(job.get("location")),
        "posted_at": _text(job.get("postedAt")),
        "contract_type": _text(job.get("contractType")),
        "experience_level": _text(job.get("experienceLevel")),
        "work_type": _text(job.get("workType")),
        "salary": _text(job.get("salary")),
        "url": _text(job.get("url")),
        "apply_url": _text(job.get("applyUrl")),
        "applicants": _text(job.get("applicants")),
        "match_score": _int_or_none(job.get("matchScore")),
        "match_reason": _text(job.get("matchReason")),
    }


def _job_out(row: dict) -> dict:
    saved_at = row.get("saved_at")
    return {
        "id": row.get("id"),
        "source": row.get("source"),
        "title": row.get("title"),
        "company": row.get("company"),
        "location": row.get("location"),
        "postedAt": row.get("posted_at"),
        "contractType": row.get("contract_type"),
        "experienceLevel": row.get("experience_level"),
        "workType": row.get("work_type"),
        "salary": row.get("salary"),
        "url": row.get("url"),
        "applyUrl": row.get("apply_url"),
        "applicants": row.get("applicants"),
        "description": row.get("description"),
        "matchScore": row.get("match_score"),
        "matchReason": row.get("match_reason"),
        "savedAt": saved_at.isoformat() if saved_at else None,
        "searchId": row.get("search_id"),
    }


def _search_out(row: dict) -> dict:
    params = row.get("params") or {}
    created = row.get("created_at")
    return {
        "id": row["id"],
        "at": created.isoformat() if created else None,
        "status": row.get("status"),
        "title": row.get("title") or params.get("title") or "Search",
        "location": f"{row.get('location') or '-'} ({row.get('country') or '-'})",
        "source": row.get("source"),
        "limit": row.get("job_limit"),
        "useAi": row.get("use_ai"),
        "model": row.get("model"),
        "count": row.get("job_count") or 0,
        "cost": float(row.get("cost") or 0),
        "skills": params.get("mustHaveSkills") or [],
        "params": params,
        "usage": row.get("usage"),
        "error": row.get("error"),
        "hasPlan": bool(row.get("has_plan")),
    }


def estimate_cost(limit: int, source: str) -> float:
    """Apify credits ka wahi estimate jo pehle frontend lagata tha."""
    sources = 2 if source == "both" else 1
    return round(limit * sources * config.COST_PER_JOB, 4)


# --------------------------- searches ---------------------------

async def start_search(*, job_description: str, limit: int, source: str, use_ai: bool, model: str) -> int | None:
    row = await db.fetch_one(
        f"""
        INSERT INTO {S}searches (job_description, source, job_limit, use_ai, model, cost, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'running')
        RETURNING id
        """,
        (job_description, source, limit, use_ai, model, estimate_cost(limit, source)),
    )
    return row["id"] if row else None


async def finish_search(search_id: int | None, *, jobs: list[dict], params: dict, usage: dict | None) -> None:
    if not search_id:
        return

    await db.execute(
        f"""
        UPDATE {S}searches
           SET status = 'done', finished_at = now(), job_count = %s,
               title = %s, location = %s, country = %s, params = %s, usage = %s
         WHERE id = %s
        """,
        (
            len(jobs),
            params.get("title"),
            params.get("location"),
            params.get("country"),
            json.dumps(params, default=str),
            json.dumps(usage, default=str) if usage else None,
            search_id,
        ),
    )
    await replace_jobs(search_id, jobs)


async def fail_search(search_id: int | None, message: str, status: str = "error") -> None:
    if not search_id:
        return
    await db.execute(
        f"UPDATE {S}searches SET status = %s, finished_at = now(), error = %s WHERE id = %s AND status = 'running'",
        (status, (message or "")[:2000], search_id),
    )


async def close_stale_searches() -> int:
    """Startup par: pichhli baar server beech me band hua to koi row 'running' me
    latki reh gayi hogi — us process ka ab koi wajood nahi, isliye band kar dete hain."""
    return await db.execute(
        f"UPDATE {S}searches SET status = 'interrupted', finished_at = now() WHERE status = 'running'",
        (),
    )


async def replace_jobs(search_id: int, jobs: list[dict]) -> None:
    """Partial aur final, dono baar yahi chalta hai — conflict par score update ho jaata hai."""
    rows = []
    for position, job in enumerate(jobs):
        row = _job_row(job)
        rows.append(
            (
                search_id, position, row["job_key"], row["source"], row["title"], row["company"],
                row["location"], row["posted_at"], row["contract_type"], row["experience_level"],
                row["work_type"], row["salary"], row["url"], row["apply_url"], row["applicants"],
                job.get("description"), row["match_score"], row["match_reason"],
            )
        )

    await db.execute_many(
        f"""
        INSERT INTO {S}jobs (
            search_id, position, job_key, source, title, company, location, posted_at,
            contract_type, experience_level, work_type, salary, url, apply_url, applicants,
            description, match_score, match_reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (search_id, job_key) DO UPDATE SET
            position = EXCLUDED.position,
            match_score = EXCLUDED.match_score,
            match_reason = EXCLUDED.match_reason,
            description = COALESCE(EXCLUDED.description, jobs.description)
        """,
        rows,
    )


async def list_searches(limit: int = 25, include_all: bool = False) -> list[dict]:
    where = "" if include_all else "WHERE s.status = 'done'"
    rows = await db.fetch_all(
        f"""
        SELECT s.*, EXISTS (SELECT 1 FROM {S}plans p WHERE p.search_id = s.id) AS has_plan
          FROM {S}searches s
          {where}
         ORDER BY s.created_at DESC
         LIMIT %s
        """,
        (limit,),
    )
    return [_search_out(row) for row in rows]


async def get_search(search_id: int) -> dict | None:
    row = await db.fetch_one(
        f"""
        SELECT s.*, EXISTS (SELECT 1 FROM {S}plans p WHERE p.search_id = s.id) AS has_plan
          FROM {S}searches s WHERE s.id = %s
        """,
        (search_id,),
    )
    if not row:
        return None

    jobs = await db.fetch_all(f"SELECT * FROM {S}jobs WHERE search_id = %s ORDER BY position ASC", (search_id,))
    plan = await db.fetch_one(
        f"SELECT plan FROM {S}plans WHERE search_id = %s ORDER BY created_at DESC LIMIT 1",
        (search_id,),
    )

    return {
        **_search_out(row),
        "jobDescription": row.get("job_description"),
        "jobs": [_job_out(job) for job in jobs],
        "plan": (plan or {}).get("plan"),
    }


async def delete_search(search_id: int) -> int:
    return await db.execute(f"DELETE FROM {S}searches WHERE id = %s", (search_id,))


async def clear_searches() -> int:
    return await db.execute(f"DELETE FROM {S}searches", ())


# --------------------------- saved jobs ---------------------------

async def list_saved() -> list[dict]:
    rows = await db.fetch_all(f"SELECT * FROM {S}saved_jobs ORDER BY saved_at DESC", ())
    return [_job_out(row) for row in rows]


async def add_saved(job: dict, search_id: int | None = None) -> dict:
    row = _job_row(job)
    saved = await db.fetch_one(
        f"""
        INSERT INTO {S}saved_jobs (
            job_key, search_id, source, title, company, location, posted_at, contract_type,
            experience_level, work_type, salary, url, apply_url, applicants, match_score, match_reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (job_key) DO UPDATE SET
            match_score = EXCLUDED.match_score,
            match_reason = EXCLUDED.match_reason,
            saved_at = now()
        RETURNING *
        """,
        (
            row["job_key"], search_id, row["source"], row["title"], row["company"], row["location"],
            row["posted_at"], row["contract_type"], row["experience_level"], row["work_type"],
            row["salary"], row["url"], row["apply_url"], row["applicants"],
            row["match_score"], row["match_reason"],
        ),
    )
    return _job_out(saved) if saved else _job_out(row)


async def remove_saved(key: str) -> int:
    return await db.execute(f"DELETE FROM {S}saved_jobs WHERE job_key = %s", (key,))


# --------------------------- plans ---------------------------

async def save_plan(*, search_id: int | None, profile: str, plan: dict, usage: dict | None, model: str) -> int | None:
    row = await db.fetch_one(
        f"""
        INSERT INTO {S}plans (search_id, profile, plan_days, model, plan, usage)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            search_id,
            profile,
            plan.get("planDays"),
            model,
            json.dumps(plan, default=str),
            json.dumps(usage, default=str) if usage else None,
        ),
    )
    return row["id"] if row else None


# --------------------------- legacy import ---------------------------

_LOC_RE = re.compile(r"^\s*(.*?)\s*\(([^)]*)\)\s*$")


def _split_location(value: Any) -> tuple[str | None, str | None]:
    """Purana frontend location ko "Bengaluru (IN)" ki tarah ek string me rakhta tha."""
    if not value:
        return None, None
    match = _LOC_RE.match(str(value))
    if not match:
        return str(value), None
    place, country = match.group(1), match.group(2)
    return (place or None), (country or None)


def _legacy_source(sources: Any) -> str:
    labels = [str(s).lower() for s in sources] if isinstance(sources, list) else []
    if len(labels) == 1:
        return "indeed" if "indeed" in labels[0] else "linkedin"
    return "both"


async def import_legacy(searches: list[dict], saved: list[dict]) -> dict:
    """localStorage ka purana data ek baar DB me daalta hai — dobara chale to duplicate nahi banta."""
    imported_searches = 0

    for item in searches or []:
        created_at = item.get("at")
        title = item.get("title") or "Search"
        exists = await db.fetch_one(
            f"SELECT id FROM {S}searches WHERE title = %s AND created_at = %s",
            (title, created_at),
        )
        if exists:
            continue

        place, country = _split_location(item.get("location"))
        jobs = item.get("jobs") or []
        source = _legacy_source(item.get("sources"))
        params = item.get("params") or {
            "title": title,
            "location": place,
            "country": country,
            "mustHaveSkills": item.get("skills") or [],
        }

        row = await db.fetch_one(
            f"""
            INSERT INTO {S}searches (
                created_at, finished_at, status, job_description, title, location, country,
                source, job_limit, use_ai, params, job_count, cost
            )
            VALUES (%s, %s, 'done', %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
            RETURNING id
            """,
            (
                created_at, created_at, "(imported from browser history)", title, place, country,
                source, item.get("limit") or config.MIN_LIMIT,
                json.dumps(params, default=str), item.get("count") or len(jobs),
                float(item.get("cost") or 0),
            ),
        )
        if row:
            await replace_jobs(row["id"], jobs)
            imported_searches += 1

    imported_saved = 0
    for job in saved or []:
        if not job:
            continue
        await add_saved(job)
        imported_saved += 1

    return {"searches": imported_searches, "saved": imported_saved}


# --------------------------- overview ---------------------------

async def stats() -> dict:
    row = await db.fetch_one(
        f"""
        SELECT
            (SELECT count(*) FROM {S}searches WHERE status = 'done')            AS searches,
            (SELECT coalesce(sum(job_count), 0) FROM {S}searches
              WHERE status = 'done')                                        AS roles,
            (SELECT coalesce(sum(cost), 0) FROM {S}searches)                    AS spend,
            (SELECT round(avg(match_score)) FROM {S}jobs
              WHERE match_score IS NOT NULL)                                 AS avg_score,
            (SELECT count(*) FROM {S}saved_jobs)                                AS saved
        """,
        (),
    ) or {}

    return {
        "searches": int(row.get("searches") or 0),
        "roles": int(row.get("roles") or 0),
        "spend": float(row.get("spend") or 0),
        "avgScore": int(row["avg_score"]) if row.get("avg_score") is not None else None,
        "saved": int(row.get("saved") or 0),
    }
