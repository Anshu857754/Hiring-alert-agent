"""Saara DB kaam yahan — routes sirf in functions ko bulate hain.

Frontend camelCase bolta hai, Postgres snake_case. Badalne ka kaam bhi yahin
hota hai taaki main.py saaf rahe.
"""
import json
import re
from typing import Any

from . import config, crypto, db
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

async def start_search(*, user_id: int, job_description: str, limit: int, source: str,
                       use_ai: bool, model: str) -> int | None:
    row = await db.fetch_one(
        f"""
        INSERT INTO {S}searches (user_id, job_description, source, job_limit, use_ai, model, cost, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'running')
        RETURNING id
        """,
        (user_id, job_description, source, limit, use_ai, model, estimate_cost(limit, source)),
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


async def list_searches(user_id: int, limit: int = 25, include_all: bool = False) -> list[dict]:
    status_filter = "" if include_all else "AND s.status = 'done'"
    rows = await db.fetch_all(
        f"""
        SELECT s.*, EXISTS (SELECT 1 FROM {S}plans p WHERE p.search_id = s.id) AS has_plan
          FROM {S}searches s
         WHERE s.user_id = %s {status_filter}
         ORDER BY s.created_at DESC
         LIMIT %s
        """,
        (user_id, limit),
    )
    return [_search_out(row) for row in rows]


async def get_search(search_id: int, user_id: int) -> dict | None:
    # user_id yahan security check hai, filter nahi — dusre ka run maangoge to
    # 404 milega, "exists but forbidden" wala hint bhi nahi.
    row = await db.fetch_one(
        f"""
        SELECT s.*, EXISTS (SELECT 1 FROM {S}plans p WHERE p.search_id = s.id) AS has_plan
          FROM {S}searches s WHERE s.id = %s AND s.user_id = %s
        """,
        (search_id, user_id),
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


async def delete_search(search_id: int, user_id: int) -> int:
    return await db.execute(
        f"DELETE FROM {S}searches WHERE id = %s AND user_id = %s", (search_id, user_id)
    )


async def clear_searches(user_id: int) -> int:
    return await db.execute(f"DELETE FROM {S}searches WHERE user_id = %s", (user_id,))


# --------------------------- saved jobs ---------------------------

async def list_saved(user_id: int) -> list[dict]:
    rows = await db.fetch_all(
        f"SELECT * FROM {S}saved_jobs WHERE user_id = %s ORDER BY saved_at DESC", (user_id,)
    )
    return [_job_out(row) for row in rows]


async def add_saved(job: dict, search_id: int | None = None, *, user_id: int) -> dict:
    row = _job_row(job)
    saved = await db.fetch_one(
        f"""
        INSERT INTO {S}saved_jobs (
            user_id, job_key, search_id, source, title, company, location, posted_at, contract_type,
            experience_level, work_type, salary, url, apply_url, applicants, match_score, match_reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, job_key) DO UPDATE SET
            match_score = EXCLUDED.match_score,
            match_reason = EXCLUDED.match_reason,
            saved_at = now()
        RETURNING *
        """,
        (
            user_id, row["job_key"], search_id, row["source"], row["title"], row["company"], row["location"],
            row["posted_at"], row["contract_type"], row["experience_level"], row["work_type"],
            row["salary"], row["url"], row["apply_url"], row["applicants"],
            row["match_score"], row["match_reason"],
        ),
    )
    return _job_out(saved) if saved else _job_out(row)


async def remove_saved(key: str, user_id: int) -> int:
    return await db.execute(
        f"DELETE FROM {S}saved_jobs WHERE job_key = %s AND user_id = %s", (key, user_id)
    )


# --------------------------- plans ---------------------------

async def save_plan(*, user_id: int, search_id: int | None, profile: str, plan: dict,
                    usage: dict | None, model: str) -> int | None:
    row = await db.fetch_one(
        f"""
        INSERT INTO {S}plans (user_id, search_id, profile, plan_days, model, plan, usage)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            user_id,
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


async def import_legacy(searches: list[dict], saved: list[dict], *, user_id: int) -> dict:
    """localStorage ka purana data ek baar DB me daalta hai — dobara chale to duplicate nahi banta."""
    imported_searches = 0

    for item in searches or []:
        created_at = item.get("at")
        title = item.get("title") or "Search"
        exists = await db.fetch_one(
            f"SELECT id FROM {S}searches WHERE title = %s AND created_at = %s AND user_id = %s",
            (title, created_at, user_id),
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
                user_id, created_at, finished_at, status, job_description, title, location, country,
                source, job_limit, use_ai, params, job_count, cost
            )
            VALUES (%s, %s, %s, 'done', %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id, created_at, created_at, "(imported from browser history)", title, place, country,
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
        await add_saved(job, user_id=user_id)
        imported_saved += 1

    return {"searches": imported_searches, "saved": imported_saved}


# --------------------------- overview ---------------------------

async def stats(user_id: int) -> dict:
    # jobs ki apni user_id nahi hai — wo hamesha apni search ke through hi
    # dikhti hain, isliye average bhi usi join se nikalta hai.
    row = await db.fetch_one(
        f"""
        SELECT
            (SELECT count(*) FROM {S}searches
              WHERE status = 'done' AND user_id = %(uid)s)                      AS searches,
            (SELECT coalesce(sum(job_count), 0) FROM {S}searches
              WHERE status = 'done' AND user_id = %(uid)s)                      AS roles,
            (SELECT coalesce(sum(cost), 0) FROM {S}searches
              WHERE user_id = %(uid)s)                                          AS spend,
            (SELECT round(avg(j.match_score)) FROM {S}jobs j
               JOIN {S}searches s ON s.id = j.search_id
              WHERE j.match_score IS NOT NULL AND s.user_id = %(uid)s)          AS avg_score,
            (SELECT count(*) FROM {S}saved_jobs WHERE user_id = %(uid)s)        AS saved
        """,
        {"uid": user_id},
    ) or {}

    return {
        "searches": int(row.get("searches") or 0),
        "roles": int(row.get("roles") or 0),
        "spend": float(row.get("spend") or 0),
        "avgScore": int(row["avg_score"]) if row.get("avg_score") is not None else None,
        "saved": int(row.get("saved") or 0),
    }


# --------------------------- reach out ---------------------------

def _outreach_out(row: dict) -> dict:
    created = row.get("created_at")
    return {
        "id": row.get("id"),
        "jobKey": row.get("job_key"),
        "searchId": row.get("search_id"),
        "at": created.isoformat() if created else None,
        "company": row.get("company"),
        "jobTitle": row.get("job_title"),
        "employees": row.get("employees"),
        "sizeBand": row.get("size_band"),
        "confidence": row.get("confidence"),
        "sizeBasis": row.get("size_basis"),
        "target": row.get("target"),
        "targetLabel": "Founder / CTO" if row.get("target") == "founder" else "HR / Recruiter",
        "targetRole": row.get("target_role"),
        "targetReason": row.get("target_why"),
        "channel": row.get("channel"),
        "subject": row.get("subject"),
        "connectionNote": row.get("connection_note"),
        "message": row.get("message"),
        "followUp": row.get("follow_up"),
        "searchUrl": row.get("search_url"),
        "model": row.get("model"),
    }


async def save_outreach(*, user_id: int, search_id: int | None, job_key: str, draft: dict,
                        usage: dict | None, model: str) -> int | None:
    row = await db.fetch_one(
        f"""
        INSERT INTO {S}outreach (
            user_id, search_id, job_key, company, job_title, employees, size_band, confidence, size_basis,
            target, target_role, target_why, channel, subject, connection_note, message,
            follow_up, search_url, model, usage
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            user_id, search_id, job_key, draft.get("company"), draft.get("jobTitle"), draft.get("employees"),
            draft.get("sizeBand"), draft.get("confidence"), draft.get("sizeBasis"),
            draft.get("target"), draft.get("targetRole"), draft.get("targetReason"),
            draft.get("channel"), draft.get("subject"), draft.get("connectionNote"),
            draft.get("message"), draft.get("followUp"), draft.get("searchUrl"), model,
            json.dumps(usage, default=str) if usage else None,
        ),
    )
    return row["id"] if row else None


async def list_outreach(search_id: int, user_id: int) -> dict[str, dict]:
    """Ek search ke saare drafts, job_key se keyed — har job ka sabse naya wala."""
    rows = await db.fetch_all(
        f"""
        SELECT DISTINCT ON (job_key) *
          FROM {S}outreach
         WHERE search_id = %s AND user_id = %s
         ORDER BY job_key, created_at DESC
        """,
        (search_id, user_id),
    )
    return {row["job_key"]: _outreach_out(row) for row in rows}


# --------------------------- sender accounts ---------------------------
# Cookie kabhi bahar nahi jaati. Row padhne ke do raaste hain:
#   _sender_out    -> UI ke liye, sirf "cookie hai ya nahi" batata hai
#   sender_secrets -> sirf connect.py ke liye, decrypt kar ke

def _sender_out(row: dict) -> dict:
    verified = row.get("last_verified_at")
    created = row.get("created_at")
    return {
        "id": row.get("id"),
        "label": row.get("label"),
        "provider": row.get("provider"),
        "hasCookie": bool(row.get("li_at_enc")),
        "isPremium": bool(row.get("is_premium")),
        "isDefault": bool(row.get("is_default")),
        "status": row.get("status"),
        "statusDetail": row.get("status_detail"),
        "lastVerifiedAt": verified.isoformat() if verified else None,
        "createdAt": created.isoformat() if created else None,
        "dailyCap": row.get("daily_cap"),
        "weeklyCap": row.get("weekly_cap"),
        "sentToday": row.get("sent_today") or 0,
        "sentThisWeek": row.get("sent_this_week") or 0,
        "noteLimit": config.NOTE_LIMIT_PREMIUM if row.get("is_premium") else config.NOTE_LIMIT_FREE,
    }


async def list_senders(user_id: int) -> list[dict]:
    rows = await db.fetch_all(
        f"""SELECT * FROM {S}sender_accounts WHERE user_id = %s
             ORDER BY is_default DESC, created_at DESC""",
        (user_id,),
    )
    return [_sender_out(row) for row in rows]


async def _sender_row(sender_id: int | None, user_id: int) -> dict | None:
    """sender_id None ho to us user ka default account — UI aksar wahi bhejta hai."""
    if sender_id:
        return await db.fetch_one(
            f"SELECT * FROM {S}sender_accounts WHERE id = %s AND user_id = %s", (sender_id, user_id)
        )
    return await db.fetch_one(
        f"""SELECT * FROM {S}sender_accounts WHERE user_id = %s
             ORDER BY is_default DESC, created_at DESC LIMIT 1""",
        (user_id,),
    )


async def get_sender(sender_id: int | None, user_id: int) -> dict | None:
    row = await _sender_row(sender_id, user_id)
    return _sender_out(row) if row else None


async def sender_secrets(sender_id: int | None, user_id: int) -> dict | None:
    """Decrypted cookie — sirf bhejte waqt. Key badal gayi ho to li_at None aayega."""
    row = await _sender_row(sender_id, user_id)
    if not row:
        return None
    return {
        **_sender_out(row),
        "li_at": crypto.unseal(row.get("li_at_enc")),
        "jsessionid": crypto.unseal(row.get("jsessionid_enc")),
        "userAgent": row.get("user_agent"),
    }


async def save_sender(
    *,
    user_id: int,
    sender_id: int | None,
    label: str,
    li_at: str | None,
    jsessionid: str | None,
    user_agent: str | None,
    is_premium: bool,
    provider: str = "apify",
    make_default: bool = True,
) -> dict | None:
    """Naya account banata hai ya purana update karta hai.

    li_at None aaye to purani cookie waise hi rehti hai — user sirf label ya
    premium flag badalna chahta hoga, har baar cookie dobara paste karwana
    bekaar hai. Nayi cookie aate hi status wapas 'unverified' ho jaata hai.
    """
    li_at_enc = crypto.seal(li_at) if li_at else None
    jsession_enc = crypto.seal(jsessionid) if jsessionid else None

    if sender_id:
        row = await db.fetch_one(
            f"""
            UPDATE {S}sender_accounts
               SET label = %s,
                   provider = %s,
                   is_premium = %s,
                   user_agent = COALESCE(%s, user_agent),
                   li_at_enc = COALESCE(%s, li_at_enc),
                   jsessionid_enc = COALESCE(%s, jsessionid_enc),
                   status = CASE WHEN %s IS NULL THEN status ELSE 'unverified' END,
                   status_detail = CASE WHEN %s IS NULL THEN status_detail ELSE NULL END
             WHERE id = %s AND user_id = %s
         RETURNING *
            """,
            (label, provider, is_premium, user_agent, li_at_enc, jsession_enc,
             li_at_enc, li_at_enc, sender_id, user_id),
        )
    else:
        row = await db.fetch_one(
            f"""
            INSERT INTO {S}sender_accounts
                (user_id, label, provider, is_premium, user_agent, li_at_enc, jsessionid_enc,
                 daily_cap, weekly_cap)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
         RETURNING *
            """,
            (user_id, label, provider, is_premium, user_agent, li_at_enc, jsession_enc,
             config.DAILY_INVITE_CAP, config.WEEKLY_INVITE_CAP),
        )

    if row and make_default:
        await set_default_sender(row["id"], user_id)
        row = await db.fetch_one(f"SELECT * FROM {S}sender_accounts WHERE id = %s", (row["id"],))

    return _sender_out(row) if row else None


async def set_default_sender(sender_id: int, user_id: int) -> None:
    # Pehle us user ka flag utaro, phir ek par lagao — ulta order partial
    # unique index par seedha constraint violation deta hai.
    await db.execute(
        f"UPDATE {S}sender_accounts SET is_default = FALSE WHERE is_default AND user_id = %s",
        (user_id,),
    )
    await db.execute(
        f"UPDATE {S}sender_accounts SET is_default = TRUE WHERE id = %s AND user_id = %s",
        (sender_id, user_id),
    )


async def mark_sender_status(sender_id: int, status: str, detail: str | None = None) -> dict | None:
    row = await db.fetch_one(
        f"""
        UPDATE {S}sender_accounts
           SET status = %s,
               status_detail = %s,
               last_verified_at = CASE WHEN %s = 'ready' THEN now() ELSE last_verified_at END
         WHERE id = %s
     RETURNING *
        """,
        (status, detail, status, sender_id),
    )
    return _sender_out(row) if row else None


async def delete_sender(sender_id: int, user_id: int) -> int:
    return await db.execute(
        f"DELETE FROM {S}sender_accounts WHERE id = %s AND user_id = %s", (sender_id, user_id)
    )


async def roll_quota(sender_id: int) -> dict | None:
    """Counters ko aaj/is hafte par le aata hai, phir taaza row lautata hai.

    date_trunc('week') Postgres me Monday deta hai. LinkedIn ki apni limit
    rolling hai, par Monday reset samajhna aasaan hai aur hamesha LinkedIn se
    zyada sakht rehta hai — yahi hum chahte hain.
    """
    row = await db.fetch_one(
        f"""
        UPDATE {S}sender_accounts
           SET sent_today = CASE WHEN day_start = CURRENT_DATE THEN sent_today ELSE 0 END,
               day_start = CURRENT_DATE,
               sent_this_week = CASE WHEN week_start = date_trunc('week', CURRENT_DATE)::date
                                     THEN sent_this_week ELSE 0 END,
               week_start = date_trunc('week', CURRENT_DATE)::date
         WHERE id = %s
     RETURNING *
        """,
        (sender_id,),
    )
    return _sender_out(row) if row else None


async def bump_sent(sender_id: int, count: int) -> None:
    if count <= 0:
        return
    await db.execute(
        f"""
        UPDATE {S}sender_accounts
           SET sent_today = sent_today + %s, sent_this_week = sent_this_week + %s
         WHERE id = %s
        """,
        (count, count, sender_id),
    )


# --------------------------- contacts ---------------------------

def _contact_out(row: dict) -> dict:
    found = row.get("discovered_at")
    sent = row.get("sent_at")
    return {
        "id": row.get("id"),
        "company": row.get("company"),
        "jobKey": row.get("job_key"),
        "searchId": row.get("search_id"),
        "fullName": row.get("full_name"),
        "headline": row.get("headline"),
        "roleTitle": row.get("role_title"),
        "location": row.get("location"),
        "profileUrl": row.get("profile_url"),
        "target": row.get("target"),
        "targetLabel": "Founder / CTO" if row.get("target") == "founder" else "HR / Recruiter",
        "seniority": row.get("seniority"),
        "employees": row.get("employees"),
        "source": row.get("source"),
        "discoveredAt": found.isoformat() if found else None,
        # Ye teen connection_requests se join ho kar aate hain — None bhi ho sakte hain.
        "requestStatus": row.get("request_status"),
        "requestError": row.get("request_error"),
        "sentAt": sent.isoformat() if sent else None,
    }


def _contact_select() -> str:
    """contacts + uska sabse naya connection request (agar hai to)."""
    return f"""
    SELECT c.*,
           r.status  AS request_status,
           r.error   AS request_error,
           r.sent_at AS sent_at
      FROM {S}contacts c
      LEFT JOIN LATERAL (
           SELECT status, error, sent_at
             FROM {S}connection_requests
            WHERE contact_id = c.id
            ORDER BY created_at DESC
            LIMIT 1
      ) r ON TRUE
    """


async def save_contacts(
    people: list[dict], *, user_id: int, job_key: str | None, search_id: int | None,
    employees: int | None,
) -> list[dict]:
    """Discovery ka output DB me.

    profile_url par upsert hota hai — dobara dhoondhne par duplicate nahi
    bante, bas details refresh ho jaati hain aur pehle bheja hua invite
    ka record bhi bacha rehta hai.
    """
    if not people:
        return []

    saved: list[dict] = []
    for person in people:
        row = await db.fetch_one(
            f"""
            INSERT INTO {S}contacts
                (user_id, search_id, job_key, company, full_name, headline, role_title, location,
                 profile_url, target, seniority, employees, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, profile_url) DO UPDATE
               SET headline   = COALESCE(EXCLUDED.headline, {S}contacts.headline),
                   role_title = COALESCE(EXCLUDED.role_title, {S}contacts.role_title),
                   company    = COALESCE(EXCLUDED.company, {S}contacts.company),
                   job_key    = COALESCE(EXCLUDED.job_key, {S}contacts.job_key),
                   target     = COALESCE(EXCLUDED.target, {S}contacts.target),
                   employees  = COALESCE(EXCLUDED.employees, {S}contacts.employees)
         RETURNING *
            """,
            (
                user_id, search_id, job_key, person.get("company"), person.get("fullName"),
                person.get("headline"), person.get("roleTitle"), person.get("location"),
                person.get("profileUrl"), person.get("target"), person.get("seniority"),
                employees, person.get("source"),
            ),
        )
        if row:
            saved.append(_contact_out(row))
    return saved


async def list_contacts(user_id: int, job_key: str | None = None, limit: int = 200) -> list[dict]:
    if job_key:
        rows = await db.fetch_all(
            _contact_select() + """ WHERE c.user_id = %s AND c.job_key = %s
                                    ORDER BY c.discovered_at DESC LIMIT %s""",
            (user_id, job_key, limit),
        )
    else:
        rows = await db.fetch_all(
            _contact_select() + " WHERE c.user_id = %s ORDER BY c.discovered_at DESC LIMIT %s",
            (user_id, limit),
        )
    return [_contact_out(row) for row in rows]


async def contacts_by_ids(ids: list[int], user_id: int) -> list[dict]:
    """user_id yahan zaroori hai — warna koi bhi id bhej kar dusre ke contact
    par invite chala sakta tha."""
    if not ids:
        return []
    rows = await db.fetch_all(
        _contact_select() + """ WHERE c.id = ANY(%s) AND c.user_id = %s
                                ORDER BY c.discovered_at DESC""",
        (ids, user_id),
    )
    return [_contact_out(row) for row in rows]


async def delete_contact(contact_id: int, user_id: int) -> int:
    return await db.execute(
        f"DELETE FROM {S}contacts WHERE id = %s AND user_id = %s", (contact_id, user_id)
    )


# --------------------------- connection requests ---------------------------

async def record_request(
    *, contact_id: int, sender_id: int | None, provider: str, note: str,
    status: str, error: str | None, run_url: str | None,
) -> int | None:
    """Har invite ka record.

    Partial unique index ek hi bande ko do baar queue/sent hone se rokta hai,
    isliye pehle uska purana failed/skipped row hata dete hain — warna retry
    kabhi insert hi nahi hoti.
    """
    await db.execute(
        f"DELETE FROM {S}connection_requests WHERE contact_id = %s AND status NOT IN ('sent', 'queued')",
        (contact_id,),
    )
    row = await db.fetch_one(
        f"""
        INSERT INTO {S}connection_requests
            (contact_id, sender_id, provider, note, status, error, run_url, sent_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, CASE WHEN %s = 'sent' THEN now() ELSE NULL END)
        ON CONFLICT DO NOTHING
     RETURNING id
        """,
        (contact_id, sender_id, provider, note, status, error, run_url, status),
    )
    return row["id"] if row else None


async def already_requested(contact_ids: list[int], user_id: int) -> set[int]:
    """Jinko pehle hi invite ja chuka hai — unhe dobara nahi bhejte."""
    if not contact_ids:
        return set()
    rows = await db.fetch_all(
        f"""
        SELECT DISTINCT r.contact_id FROM {S}connection_requests r
          JOIN {S}contacts c ON c.id = r.contact_id
         WHERE r.contact_id = ANY(%s) AND c.user_id = %s AND r.status IN ('sent', 'queued')
        """,
        (contact_ids, user_id),
    )
    return {row["contact_id"] for row in rows}
