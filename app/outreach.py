"""Founder-ya-HR ka faisla aur us insaan tak pahunchne ka raasta.

Rule model par nahi chhoda gaya — wo ek business rule hai, isliye code me hai:
chhoti company (< FOUNDER_MAX_EMPLOYEES) me seedha founder, badi me HR.
LLM sirf company size estimate karta hai aur usi hisaab se message likhta hai;
yahan hum uska estimate le kar final target khud tay karte hain.
"""
from urllib.parse import quote_plus

from . import config

FOUNDER = "founder"
HR = "hr"

# Founder route par in titles me se koi bhi kaam karega.
FOUNDER_TITLES = "Founder OR Co-founder OR CTO OR CEO"
HR_TITLES = "Recruiter OR Talent OR HR"


def decide_target(employees: int | None, confidence: str) -> tuple[str, str]:
    """(target, reason) — threshold config se aata hai."""
    limit = config.FOUNDER_MAX_EMPLOYEES

    if employees is None:
        return HR, "Company size could not be estimated, so HR is the safer route"
    if confidence == "low":
        return (
            (FOUNDER, f"Looks small (~{employees}), but the estimate is uncertain — verify before sending")
            if employees < limit
            else (HR, f"Looks large (~{employees}), so HR is the safer route")
        )
    if employees < limit:
        return FOUNDER, f"About {employees} employees — under {limit}, so the founder still reads inbound"
    return HR, f"About {employees} employees — at this size hiring runs through HR"


def people_search_url(company: str | None, target: str) -> str:
    """LinkedIn ka people search — sahi insaan khud dhoondhne ke liye.

    Hum contact details nahi nikaalte: search link deta hai, kis par click karna
    hai wo tum decide karte ho.
    """
    titles = FOUNDER_TITLES if target == FOUNDER else HR_TITLES
    keywords = f"{company} {titles}" if company else titles
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(keywords)}"


def finalize(draft: dict, job: dict) -> dict:
    """LLM ke draft par apna rule chipka kar poora reach-out object banata hai."""
    target, reason = decide_target(draft.get("employees"), draft.get("confidence") or "low")

    # Model ne kisi aur ko address kiya ho to bata dete hain — message tab bhi
    # kaam ka rehta hai, par user ko pata hona chahiye ki tone mismatch ho sakti hai.
    role = (draft.get("targetRole") or "").lower()
    guessed = FOUNDER if any(w in role for w in ("founder", "ceo", "co-founder")) else HR
    adjusted = guessed != target

    # Mismatch par model ka title nahi dikhate — warna chip "HR / Recruiter"
    # kehti aur uske bagal me "Founder" likha hota. Rule jeetta hai; message ki
    # tone ka mismatch alag se warning me bata dete hain.
    target_role = draft.get("targetRole") or ""
    if adjusted or not target_role:
        target_role = "Founder / CTO" if target == FOUNDER else "Talent / HR"

    return {
        **draft,
        "company": job.get("company"),
        "jobTitle": job.get("title"),
        "target": target,
        "targetLabel": "Founder / CTO" if target == FOUNDER else "HR / Recruiter",
        "targetRole": target_role,
        "targetReason": reason,
        "threshold": config.FOUNDER_MAX_EMPLOYEES,
        "targetAdjusted": adjusted,
        "searchUrl": people_search_url(job.get("company"), target),
    }
