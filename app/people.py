"""Company ke decision makers Apify se nikaalta hai.

Rule wahi hai jo outreach.py me hai — chhoti company me founder/CTO, badi me
HR — bas ab hum search link dene ke bajaye asli log laate hain.

Discovery ke liye cookie nahi chahiye: ye actors sirf public profile data
padhte hain. Cookie sirf bhejne ke waqt lagti hai (app/connect.py).

Actor ke input field names uske store page se aate hain aur developer kabhi
bhi badal sakta hai. Isliye:
  * input `_ACTOR_INPUTS` me alag rakha hai — naya actor lagana ho to yahin ek
    entry jodo, baaki code haath na lagao;
  * output normalizer kai spellings maanta hai (fullName/name, linkedinUrl/
    profileUrl/url), kyunki har actor apna naam rakhta hai.
"""
import logging
import re
from typing import Any

from apify_client import ApifyClientAsync

from . import config
from .outreach import FOUNDER, HR

log = logging.getLogger("hiring-agent.people")

# Kis bucket me kaunse titles dhoondhne hain. outreach.py ke FOUNDER_TITLES/
# HR_TITLES ka hi list version — actors ko OR-string nahi, alag lines chahiye.
FOUNDER_TITLES = ["Founder", "Co-Founder", "CEO", "CTO"]
HR_TITLES = ["Recruiter", "Talent Acquisition", "HR Manager", "Head of People", "Technical Recruiter"]

# Headline padh kar bucket tay karne ke liye. Founder pehle check hota hai —
# "Founder & Head of People" wale ko founder hi maanna theek hai.
_FOUNDER_RE = re.compile(r"\b(founder|co[- ]?founder|ceo|cto|chief\s+\w+\s+officer|owner|managing director)\b", re.I)
_HR_RE = re.compile(r"\b(recruit\w*|talent|hr\b|human resources|people ops|people operations|hiring|staffing)\b", re.I)

_SENIOR_RE = re.compile(r"\b(head|chief|vp|vice president|director|lead|principal|senior|manager)\b", re.I)


def titles_for(target: str) -> list[str]:
    return FOUNDER_TITLES if target == FOUNDER else HR_TITLES


def classify(headline: str | None) -> tuple[str | None, str]:
    """(target, seniority) — headline se. Kuch match na ho to target None."""
    text = headline or ""
    seniority = "senior" if _SENIOR_RE.search(text) else "individual"
    if _FOUNDER_RE.search(text):
        return FOUNDER, "founder"
    if _HR_RE.search(text):
        return HR, seniority
    return None, seniority


def _first(row: dict, *keys: str) -> Any:
    """Pehli key jiski value khaali na ho — actors ke alag-alag naam sambhalne ke liye."""
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def _normalize(row: dict, *, target: str) -> dict | None:
    url = _first(row, "linkedinUrl", "profileUrl", "profileURL", "url", "link", "publicProfileUrl")
    name = _first(row, "fullName", "name", "displayName")

    if not name:
        first = _first(row, "firstName") or ""
        last = _first(row, "lastName") or ""
        name = f"{first} {last}".strip() or None

    # Profile URL hi hamari pehchaan hai (contacts table me unique). Uske bina
    # row bekaar hai — invite kis par bhejenge?
    if not url or not name:
        return None

    headline = _first(row, "headline", "currentRole", "jobTitle", "title", "position", "occupation")
    detected, seniority = classify(headline)

    return {
        "fullName": str(name).strip(),
        "headline": str(headline).strip() if headline else None,
        "roleTitle": str(_first(row, "currentRole", "jobTitle", "position") or headline or "").strip() or None,
        "location": str(_first(row, "location", "locationName", "geoRegion") or "").strip() or None,
        "profileUrl": str(url).split("?")[0].rstrip("/"),
        # Yahan sirf actor ka diya hua company naam — jo humne maanga tha wo
        # fallback me daalna filter ko andha kar deta hai (har row match ho jaati).
        # Display ke liye fallback filter paas hone ke baad lagta hai.
        "company": str(_first(row, "company", "companyName") or "").strip() or None,
        # Actor ne jo bhi diya, headline se nikla bucket zyada bharosemand hai.
        # Kuch na mile to wahi bucket maan lo jo hum dhoondhne gaye the.
        "target": detected or target,
        "seniority": seniority,
        "source": "apify",
    }


def _actor_input(actor: str, *, company: str, titles: list[str], location: str | None, limit: int) -> dict:
    """Har actor apne input keys maangta hai — mapping ek hi jagah rehti hai."""
    if actor.startswith("apt_marble/"):
        return {
            "jobTitles": titles,
            "keywords": [company],
            "locations": [location] if location else [],
            "maxResults": limit,
            "dedupe": True,
        }
    if actor.startswith("memo23/"):
        return {
            "startUrls": [{"url": f"https://www.linkedin.com/company/{_slug(company)}/people/"}],
            "positions": titles,
            "maxItems": limit,
        }
    # Anjaan actor — sabse aam keys bhej dete hain aur error user tak jaata hai.
    return {"keywords": [company], "jobTitles": titles, "maxItems": limit}


def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")

# Company ke naam me ye shabd kuch nahi batate — match karte waqt hata dete hain.
_COMPANY_NOISE = {
    "the", "inc", "inc.", "llc", "ltd", "ltd.", "limited", "pvt", "private",
    "corp", "corporation", "co", "company", "technologies", "technology",
    "tech", "labs", "lab", "solutions", "systems", "software", "services",
    "group", "global", "india", "gmbh", "sa", "bv", "plc",
}


def _company_tokens(company: str) -> set[str]:
    words = re.split(r"[^a-z0-9]+", (company or "").lower())
    return {w for w in words if w and w not in _COMPANY_NOISE and len(w) > 2}


def works_at(person: dict, company: str) -> bool:
    """Ye insaan sach me us company me hai ya nahi.

    Zaroori hai kyunki keyword-search actors company ko filter nahi karte —
    "Zerodha" maango to duniya bhar ke founders aa jaate hain. Aise kisi ko
    "aapki company me role dekha" wala note bhejna sabse bura outcome hai:
    galat aadmi, galat baat, aur account ka risk alag.

    Match udaar nahi hai — company ka koi ek asli token headline ya company
    field me dikhna chahiye.
    """
    wanted = _company_tokens(company)
    if not wanted:
        return False

    haystack = " ".join(
        str(person.get(field) or "").lower()
        for field in ("company", "headline", "roleTitle")
    )
    found = set(re.split(r"[^a-z0-9]+", haystack))
    return bool(wanted & found)


async def find_decision_makers(
    *,
    company: str,
    target: str,
    location: str | None = None,
    limit: int = 10,
    token: str,
    actor: str | None = None,
) -> list[dict]:
    """Ek company ke liye decision makers. Fail ho to khaali list — route 502 nahi karta."""
    if not company:
        return []

    actor_id = actor or config.PEOPLE_ACTOR
    titles = titles_for(target)
    run_input = _actor_input(actor_id, company=company, titles=titles, location=location, limit=limit)

    client = ApifyClientAsync(token=token)
    run = await client.actor(actor_id).call(run_input=run_input)
    if run is None or not run.default_dataset_id:
        raise RuntimeError(f"Apify actor {actor_id} returned no dataset (it failed or timed out)")

    page = await client.dataset(run.default_dataset_id).list_items()

    people: list[dict] = []
    dropped = 0
    seen: set[str] = set()
    for item in page.items:
        person = _normalize(item, target=target)
        if not person or person["profileUrl"] in seen:
            continue
        seen.add(person["profileUrl"])

        # Actor ka keyword search company par filter nahi karta — "Zerodha"
        # maango to kisi aur company ka founder bhi aa jaata hai. Aise logon ko
        # rakhna matlab galat aadmi ko galat note bhejna, isliye yahin gira dete hain.
        if not works_at(person, company):
            dropped += 1
            continue

        # Filter paas — ab display ke liye company bhar sakte hain.
        person["company"] = person["company"] or company
        people.append(person)

    if dropped:
        log.info("%s: %s profile(s) dropped — they do not work at this company", company, dropped)

    # Jo bucket humne maanga tha wo pehle — baaki neeche, phenke nahi jaate
    # kyunki chhoti company me "Founder" headline kabhi kabhi missing hoti hai.
    people.sort(key=lambda p: 0 if p["target"] == target else 1)
    return people[:limit]
