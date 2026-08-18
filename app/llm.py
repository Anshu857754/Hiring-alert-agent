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
    """`reasoning.enabled=False` yahan latency ka sabse bada lever hai.

    DeepSeek v4 Pro reasoning model hai aur bina roke output ka ~75% andar hi
    andar sochne me laga deta hai. Cache-free benchmark (har call me alag nonce):

        baseline                    3102 completion tokens, 2353 reasoning
        reasoning_effort="low"      3440 / 2680   <- asar nahi padta
        reasoning.max_tokens=150    5287 / 4654   <- cap ignore ho jaata hai
        reasoning.enabled=False      654 / 0      <- output 79% kam

    Model ~70-95 tok/s deta hai, to token count hi wall-clock time hai. Yahan ke
    teeno kaam (JD parse, rubric scoring, plan) structured output hain — chain of
    thought inke liye zaroori nahi, aur JSON schema dono soorat me valid rehta hai.
    """
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
                "reasoning": {"enabled": False},
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
        raise RuntimeError("OpenRouter returned an empty response")

    # Model kabhi kabhi JSON ko ```json fence me wrap kar deta hai.
    cleaned = _FENCE_END.sub("", _FENCE_START.sub("", content.strip()))
    usage = dict(data.get("usage") or {})
    usage["provider"] = data.get("provider")  # latency debug karne ke liye
    return json.loads(cleaned), usage


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
You MUST return one entry for every posting number given.
Score directly from the guide - do not deliberate at length."""


def _compact_job(job: dict, index: int) -> str:
    """Poore descriptions bhejne se tokens bahut lagte hain, isliye trim karke bhejte hain."""
    description = re.sub(r"\s+", " ", job.get("description") or "")[:450]
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
                await on_progress("score", f"Batch {batch_no + 1} could not be scored: {err}", True)

        done += 1
        if on_progress:
            await on_progress("score", f"AI matching: {done}/{len(batches)} batches done")

    await asyncio.gather(*(run_batch(i, batch) for i, batch in enumerate(batches)))

    scored = []
    for i, job in enumerate(jobs):
        hit = scores.get(i)
        scored.append({**job, "matchScore": hit["score"] if hit else None, "matchReason": hit["reason"] if hit else None})

    return {"jobs": scored, "usage": usage_total}


RECOMMEND_PROMPT = """You are a career coach for a job seeker. You get the seeker's profile (a resume or self-description) and job postings that were already matched and scored against that profile.

Your job: find the skills that keep the seeker OUT of the near-miss postings, then design a focused study plan that would realistically lift those matches.

Rules:
- Only recommend skills that actually appear in the supplied postings. Never invent requirements.
- Focus on near-miss postings (roughly 40-75 score). Ignore postings that already match strongly, and ignore ones from a completely different career track.
- Choose planDays yourself: 15 when the gaps are shallow (one framework, one tool, one library), 30 when they need real depth (a new language, distributed systems, cloud infrastructure). Return only 15 or 30.
- Be honest. If a posting demands years of experience that no short plan can create, put it in notRealistic instead of promising it.
- projectedScore is a realistic estimate after the plan, not a guarantee. It must be higher than currentScore but stay believable.

Return ONLY a JSON object:
{
  "planDays": 15 or 30,
  "rationale": "one sentence on why that length",
  "summary": "two sentences on where the seeker stands right now",
  "strengths": ["skill the profile already shows", ...],
  "gaps": [{"skill": "...", "postings": <how many supplied postings ask for it>, "why": "max 15 words"}],
  "milestones": [{"window": "Day 1-5", "focus": "...", "outcome": "what you can show at the end", "practice": "one concrete thing to build"}],
  "unlocks": [{"title": "...", "company": "...", "currentScore": 64, "projectedScore": 80, "needs": ["skill", ...]}],
  "notRealistic": ["posting title - why a short plan will not close it", ...]
}

Limits: strengths max 5, gaps max 4 (most valuable first), milestones exactly 4 covering the whole planDays, unlocks max 3 (only postings from the input), notRealistic max 2 (may be empty).
Keep every string tight: summary max 40 words, why max 12 words, focus max 8 words, practice and outcome max 18 words each. Answer directly - do not deliberate at length."""


def _compact_for_plan(job: dict, index: int) -> str:
    description = re.sub(r"\s+", " ", job.get("description") or "")[:400]
    return "\n".join(
        [
            f"#{index}",
            f"Title: {job.get('title') or '-'}",
            f"Company: {job.get('company') or '-'}",
            f"Score against profile: {job.get('matchScore') if job.get('matchScore') is not None else 'not scored'}",
            f"Level: {job.get('experienceLevel') or '-'}",
            f"Requirements: {description}",
        ]
    )


async def build_learning_plan(profile: str, jobs: list[dict], api_key: str) -> dict[str, Any]:
    """Near-miss postings ko dekh kar skill gaps aur 15/30 din ka plan nikaalta hai."""
    # Sirf near-miss zone ke aas-paas wali postings bhejte hain — plan unhi par bana
    # hai, to poori list bhejna tokens aur latency dono barbaad karta hai.
    ranked = sorted(jobs, key=lambda j: j.get("matchScore") if j.get("matchScore") is not None else -1, reverse=True)
    relevant = [j for j in ranked if (j.get("matchScore") or 0) >= 30] or ranked
    listing = "\n\n".join(_compact_for_plan(job, i) for i, job in enumerate(relevant[:12]))

    data, usage = await _chat(
        [
            {"role": "system", "content": RECOMMEND_PROMPT},
            {"role": "user", "content": f"SEEKER PROFILE:\n{profile[:6000]}\n\n---\n\nMATCHED POSTINGS:\n{listing}"},
        ],
        api_key,
        temperature=0.4,
    )

    days = data.get("planDays")
    if days not in (15, 30):
        days = 30

    def _clip(key: str, limit: int) -> list:
        value = data.get(key)
        return value[:limit] if isinstance(value, list) else []

    return {
        "plan": {
            "planDays": days,
            "rationale": data.get("rationale") or "",
            "summary": data.get("summary") or "",
            "strengths": _clip("strengths", 6),
            "gaps": _clip("gaps", 5),
            "milestones": _clip("milestones", 5),
            "unlocks": _clip("unlocks", 5),
            "notRealistic": _clip("notRealistic", 3),
        },
        "usage": usage,
    }


OUTREACH_PROMPT = """You are helping a job seeker send ONE personal outreach message about a specific job posting they want.

You get: the posting, the company name, and the seeker's own profile/resume.

Step 1 — company size. Estimate how many employees the company has today. Use what you know about the company; if the name is unfamiliar or ambiguous, say so honestly instead of guessing a precise number.

Step 2 — pick who to write to, using this rule:
- fewer than {threshold} employees -> the founder / CEO
- {threshold} or more -> an HR / talent / recruiting person
- genuinely unsure of the size -> HR / talent

Step 3 — write the message for that person. A founder note and an HR note are not the same: founders respond to what you can build for them and why their specific product interests you; HR responds to how cleanly you fit the requirements they published.

Return ONLY a JSON object:
{{
  "employees": <integer best estimate, or null if you truly do not know>,
  "sizeBand": "1-10" | "11-50" | "51-200" | "201-500" | "501-1000" | "1000+" | "unknown",
  "confidence": "high" | "medium" | "low",
  "sizeBasis": "max 15 words on what your estimate is based on",
  "targetRole": "the exact job title to look for, e.g. 'Founder & CEO' or 'Talent Acquisition Lead'",
  "targetWhy": "max 20 words on why this person, for this company",
  "channel": "LinkedIn DM" | "Email" | "LinkedIn connection request",
  "subject": "email-style subject line, max 8 words",
  "connectionNote": "LinkedIn connection request note, HARD LIMIT 280 characters",
  "message": "the full message, 90-150 words",
  "followUp": "one-line follow-up to send after 5-7 days if there is no reply"
}}

Rules for the message:
- Open with something specific to THIS company or role. Never "I came across your job posting" alone.
- Name two or three things from the seeker's profile that map to what the posting actually asks for. Use only what is in the profile — never invent experience, numbers, or employers.
- One clear ask at the end (a short call, or whether they are open to reviewing a profile).
- No flattery, no buzzwords, no "I am writing to express my keen interest". Plain sentences a real person would send.
- If the profile is thin on what the posting needs, be honest about the angle rather than overclaiming."""


def _outreach_user_msg(job: dict, profile: str) -> str:
    description = re.sub(r"\s+", " ", job.get("description") or "")[:1200]
    return "\n".join(
        [
            f"COMPANY: {job.get('company') or 'unknown'}",
            f"ROLE: {job.get('title') or '-'}",
            f"LOCATION: {job.get('location') or '-'}",
            f"LEVEL: {job.get('experienceLevel') or '-'}",
            f"POSTING: {description or '(no description was scraped)'}",
            "",
            "---",
            "",
            f"SEEKER PROFILE:\n{profile[:5000]}",
        ]
    )


async def draft_outreach(job: dict, profile: str, api_key: str, threshold: int = 150) -> dict[str, Any]:
    """Ek posting ke liye reach-out draft banata hai.

    Founder-ya-HR ka faisla yahan se nahi hota — wo store/route me threshold se
    tay hota hai. Model sirf size estimate karta hai aur usi hisaab se likhta hai.
    """
    data, usage = await _chat(
        [
            {"role": "system", "content": OUTREACH_PROMPT.format(threshold=threshold)},
            {"role": "user", "content": _outreach_user_msg(job, profile)},
        ],
        api_key,
        temperature=0.5,
    )

    employees = data.get("employees")
    if not isinstance(employees, int) or employees <= 0:
        employees = None

    confidence = str(data.get("confidence") or "low").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    note = (data.get("connectionNote") or "").strip()
    if len(note) > 300:  # model kabhi kabhi limit cross kar deta hai
        note = note[:297].rsplit(" ", 1)[0] + "..."

    return {
        "draft": {
            "employees": employees,
            "sizeBand": data.get("sizeBand") or "unknown",
            "confidence": confidence,
            "sizeBasis": (data.get("sizeBasis") or "").strip(),
            "targetRole": (data.get("targetRole") or "").strip(),
            "targetWhy": (data.get("targetWhy") or "").strip(),
            "channel": (data.get("channel") or "LinkedIn DM").strip(),
            "subject": (data.get("subject") or "").strip(),
            "connectionNote": note,
            "message": (data.get("message") or "").strip(),
            "followUp": (data.get("followUp") or "").strip(),
        },
        "usage": usage,
    }
