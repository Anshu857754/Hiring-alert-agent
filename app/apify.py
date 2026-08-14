"""Apify actors chalata hai aur dono sources ka output ek jaise shape me laata hai."""
import asyncio
from typing import Any, Awaitable, Callable

from apify_client import ApifyClientAsync

# bebity/linkedin-jobs-scraper ke liye paid rental chahiye; ye pay-per-event actor free plan par chalta hai.
LINKEDIN_ACTOR = "curious_coder/linkedin-jobs-scraper"
INDEED_ACTOR = "misceres/indeed-scraper"

ProgressFn = Callable[..., Awaitable[None]]


def _normalize_linkedin(job: dict) -> dict:
    return {
        "source": "linkedin",
        "title": job.get("title"),
        "company": job.get("companyName"),
        "location": job.get("location"),
        "postedAt": job.get("postedAt") or job.get("publishedAt"),
        "contractType": job.get("employmentType") or None,
        "experienceLevel": job.get("seniorityLevel") or None,
        "workType": job.get("workplaceType") or None,
        "salary": job.get("salary") or None,
        "url": job.get("link") or job.get("jobUrl"),
        "applyUrl": job.get("applyUrl") or None,
        "applicants": job.get("applicantsCount") or None,
        "description": job.get("descriptionText") or job.get("description"),
    }


def _normalize_indeed(job: dict) -> dict:
    job_type = job.get("jobType")
    return {
        "source": "indeed",
        "title": job.get("positionName"),
        "company": job.get("company"),
        "location": job.get("location"),
        "postedAt": job.get("postedAt") or job.get("postingDateParsed"),
        "contractType": ", ".join(job_type) if isinstance(job_type, list) else job_type,
        "experienceLevel": None,
        "workType": "Remote" if job.get("isRemote") else None,
        "salary": job.get("salary"),
        "url": job.get("url"),
        "applyUrl": job.get("externalApplyLink"),
        "applicants": None,
        "description": job.get("description"),
    }


async def scrape_jobs(
    *,
    title: str,
    location: str,
    country: str,
    limit: int,
    source: str = "both",
    token: str,
    on_progress: ProgressFn | None = None,
) -> list[dict[str, Any]]:
    """Dono job boards ko parallel me scrape karta hai, phir URL par dedupe."""
    client = ApifyClientAsync(token=token)

    async def progress(stage: str, message: str, is_error: bool = False) -> None:
        if on_progress:
            await on_progress(stage, message, is_error)

    async def run_one(actor_id: str, run_input: dict, label: str, normalize) -> list[dict]:
        await progress(label, f"{label} scraper start ho raha hai...")
        try:
            run = await client.actor(actor_id).call(run_input=run_input)
            if run is None or not run.default_dataset_id:
                raise RuntimeError("Apify run ka dataset nahi mila (run fail hua ya timeout)")
            page = await client.dataset(run.default_dataset_id).list_items()
            items = page.items
            await progress(label, f"{label} se {len(items)} jobs mile")
            return [normalize(item) for item in items]
        except Exception as err:  # ek source fail ho to dusri ka data phir bhi dikhao
            await progress(label, f"{label} fail hua: {err}", True)
            return []

    tasks = []

    if source in ("both", "linkedin"):
        tasks.append(
            run_one(
                LINKEDIN_ACTOR,
                {"keywords": title, "location": location, "limitPerSource": limit, "scrapeCompany": False},
                "linkedin",
                _normalize_linkedin,
            )
        )

    if source in ("both", "indeed"):
        tasks.append(
            run_one(
                INDEED_ACTOR,
                {
                    "position": title,
                    "location": location,
                    "country": country,
                    "maxItemsPerSearch": limit,
                    "parseCompanyDetails": False,
                    "saveOnlyUniqueItems": True,
                    "followApplyRedirects": False,
                },
                "indeed",
                _normalize_indeed,
            )
        )

    seen: set[str] = set()
    jobs: list[dict] = []
    for batch in await asyncio.gather(*tasks):
        for job in batch:
            url = job.get("url")
            if url:
                if url in seen:
                    continue
                seen.add(url)
            jobs.append(job)
    return jobs
