"""OpenRouter calls — JD parse karna aur jobs ko score karna."""
import asyncio
import json
import re
from typing import Any, Awaitable, Callable

import httpx

MODEL_ID = "deepseek/deepseek-v4-pro"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

ProgressFn = Callable[..., Awaitable[None]]

_FENCE_START = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_END = re.compile(r"```$")


async def _chat(messages: list[dict], api_key: str, temperature: float = 0.2) -> tuple[dict, dict]:
    async with httpx.AsyncClient(timeout=180.0) as client:
        res = await client.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Title": "Hiring Agent",
            },
            json={
                "model": MODEL_ID,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )

    if res.status_code >= 400:
        raise RuntimeError(f"OpenRouter {res.status_code}: {res.text[:300]}")

    data = res.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        content = None
    if not content:
        raise RuntimeError("OpenRouter ne khaali response bheja")

    # Model kabhi kabhi JSON ko ```json fence me wrap kar deta hai.
    cleaned = _FENCE_END.sub("", _FENCE_START.sub("", content.strip()))
    return json.loads(cleaned), data.get("usage") or {}


EXTRACT_PROMPT = """You are a recruitment search assistant. Read the job description and extract search parameters for scraping LinkedIn and Indeed.

Return ONLY a JSON object with these keys:
- "title": the most effective short search keyword string (2-5 words) for a job board. Use the common market job title, not the company's fancy internal title.
- "location": city or region name as typed on a job board. If the JD is remote or has no location, use the country name.
- "country": ISO 3166-1 alpha-2 country code (e.g. "IN", "US", "GB"). Default "IN" if truly unclear.
- "seniority": one of "internship", "entry", "mid", "senior", "lead", "unknown".
- "mustHaveSkills": array of up to 8 key technical skills mentioned.
- "summary": one short sentence describing what role is being searched for."""


async def extract_search_params(job_description: str, api_key: str) -> dict[str, Any]:
    data, usage = await _chat(
        [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": job_description},
        ],
        api_key,
    )

    skills = data.get("mustHaveSkills")
    return {
        "params": {
            "title": data.get("title") or "Software Engineer",
            "location": data.get("location") or "India",
            "country": (data.get("country") or "IN").upper()[:2],
            "seniority": data.get("seniority") or "unknown",
            "mustHaveSkills": skills if isinstance(skills, list) else [],
            "summary": data.get("summary") or "",
        },
        "usage": usage,
    }


SCORE_PROMPT = """You are a recruitment matching engine. You get a target job description and a numbered list of scraped job postings.

For EACH posting, judge how well it matches the target job description.

Return ONLY a JSON object of the form:
{"results": [{"i": <the posting number>, "score": <integer 0-100>, "reason": "<max 12 words explaining the score>"}]}

Scoring guide: 90+ near-identical role and seniority; 70-89 strong match with minor gaps; 50-69 related but different seniority/stack; below 50 weak match.
You MUST return one entry for every posting number given."""


def _compact_job(job: dict, index: int) -> str:
    """Poore descriptions bhejne se tokens bahut lagte hain, isliye trim karke bhejte hain."""
    description = re.sub(r"\s+", " ", job.get("description") or "")[:700]
    return "\n".join(
        [
            f"#{index}",
            f"Title: {job.get('title') or '-'}",
            f"Company: {job.get('company') or '-'}",
            f"Location: {job.get('location') or '-'}",
            f"Type: {job.get('contractType') or '-'} | Level: {job.get('experienceLevel') or '-'}",
            f"Description: {description}",
        ]
    )


async def score_jobs(
    job_description: str,
    jobs: list[dict],
    api_key: str,
    batch_size: int = 15,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Jobs ko chhote batches me parallel score karta hai taaki ek request badi na ho."""
    batches = [jobs[i : i + batch_size] for i in range(0, len(jobs), batch_size)]
    scores: dict[int, dict] = {}
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0}
    done = 0

    async def run_batch(batch_no: int, batch: list[dict]) -> None:
        nonlocal done
        offset = batch_no * batch_size
        listing = "\n\n".join(_compact_job(job, offset + k) for k, job in enumerate(batch))

        try:
            data, usage = await _chat(
                [
                    {"role": "system", "content": SCORE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"TARGET JOB DESCRIPTION:\n{job_description[:6000]}\n\n"
                            f"---\n\nPOSTINGS:\n{listing}"
                        ),
                    },
                ],
                api_key,
            )
            for row in data.get("results") or []:
                if isinstance(row.get("i"), int):
                    try:
                        score = int(row.get("score") or 0)
                    except (TypeError, ValueError):
                        score = 0
                    scores[row["i"]] = {"score": score, "reason": row.get("reason") or ""}
            usage_total["prompt_tokens"] += usage.get("prompt_tokens") or 0
            usage_total["completion_tokens"] += usage.get("completion_tokens") or 0
        except Exception as err:  # ek batch fail ho to baaki chalte rahein
            if on_progress:
                await on_progress("score", f"Batch {batch_no + 1} score nahi ho paya: {err}", True)

        done += 1
        if on_progress:
            await on_progress("score", f"AI matching: {done}/{len(batches)} batches done")

    await asyncio.gather(*(run_batch(i, batch) for i, batch in enumerate(batches)))

    scored = []
    for i, job in enumerate(jobs):
        hit = scores.get(i)
        scored.append({**job, "matchScore": hit["score"] if hit else None, "matchReason": hit["reason"] if hit else None})

    return {"jobs": scored, "usage": usage_total}
