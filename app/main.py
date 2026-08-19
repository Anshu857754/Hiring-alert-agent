"""FastAPI backend — search stream, PDF extract, Postgres persistence, aur static frontend."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, docs, outreach, store
from .auth import BasicAuth
from .apify import scrape_jobs
from .llm import MODEL_ID, build_learning_plan, draft_outreach, extract_search_params, score_jobs

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("hiring-agent")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Server start hote hi pending migrations chal jaate hain — alag se
    # kuch chalane ki zaroorat nahi. DB na mile to app phir bhi chalti hai.
    applied = await db.connect()
    if applied:
        log.info("migrations applied: %s", ", ".join(applied))
    if db.enabled():
        stale = await store.close_stale_searches()
        if stale:
            log.info("%s interrupted search(es) from a previous run marked closed", stale)
        log.info("database ready (schema: %s)", config.DB_SCHEMA)
    yield
    await db.close()


app = FastAPI(title="Hiring Agent", version="2.1.0", lifespan=lifespan)


class SearchRequest(BaseModel):
    jobDescription: str = ""
    limit: int = config.MIN_LIMIT
    source: Literal["both", "linkedin", "indeed"] = "both"
    useAi: bool = True
    # UI ka "Target role" field + seniority prefix. Set ho to LLM ka nikala
    # hua title ignore karke yahi keyword scrape hota hai.
    titleOverride: str | None = None
    # Chhote batches parallel me chalte hain, to wall-clock time sabse dheeme
    # single call se bandha hota hai — 10 par wo call 15 se choti hoti hai.
    batchSize: int = Field(default=10, ge=5, le=30)


class RecommendRequest(BaseModel):
    profile: str = ""
    jobs: list[dict] = Field(default_factory=list)
    searchId: int | None = None


class SaveRequest(BaseModel):
    job: dict = Field(default_factory=dict)
    searchId: int | None = None


class OutreachRequest(BaseModel):
    job: dict = Field(default_factory=dict)
    profile: str = ""
    searchId: int | None = None


class ImportRequest(BaseModel):
    """Purana localStorage data ek baar DB me daalne ke liye."""
    searches: list[dict] = Field(default_factory=list)
    saved: list[dict] = Field(default_factory=list)


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "model": MODEL_ID,
        "apifyKey": bool(config.APIFY_API_KEY),
        "openRouterKey": bool(config.OPENROUTER_API_KEY),
        "db": db.status(),
    }


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)) -> JSONResponse:
    """PDF/DOCX se JD ka text nikaalta hai — markitdown local chalta hai, koi LLM cost nahi."""
    data = await file.read()

    if not data:
        return JSONResponse({"error": "The file is empty"}, status_code=400)
    if len(data) > config.MAX_UPLOAD_BYTES:
        mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        return JSONResponse({"error": f"File is larger than {mb} MB"}, status_code=400)

    try:
        result = await docs.extract_text(file.filename or "", data)
    except docs.UnsupportedFile as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    except Exception as err:
        return JSONResponse({"error": f"Could not read the file: {err}"}, status_code=422)

    if not result["text"].strip():
        return JSONResponse(
            {"error": "No text found in this file — it may be a scanned PDF (images only)."},
            status_code=422,
        )

    return JSONResponse({**result, "filename": file.filename})


@app.post("/api/recommend")
async def recommend(req: RecommendRequest) -> JSONResponse:
    """Scored postings ke gaps se 15/30 din ka upskilling plan banata hai."""
    profile = (req.profile or "").strip()

    if len(profile) < 20:
        return JSONResponse({"error": "Add your resume or profile first (at least 20 characters)"}, status_code=400)
    if not req.jobs:
        return JSONResponse({"error": "Run a search first — there are no postings to analyse"}, status_code=400)
    if not config.OPENROUTER_API_KEY:
        return JSONResponse({"error": "OPENROUTER_API_KEY not found in .env"}, status_code=500)

    try:
        result = await build_learning_plan(profile, req.jobs, config.OPENROUTER_API_KEY)
    except Exception as err:
        return JSONResponse({"error": f"Could not build a plan: {err}"}, status_code=502)

    # Plan bhi search ke saath DB me rehta hai — history kholte hi wapas mil jaata hai.
    try:
        await store.save_plan(
            search_id=req.searchId,
            profile=profile,
            plan=result["plan"],
            usage=result.get("usage"),
            model=MODEL_ID,
        )
    except Exception as err:
        log.warning("plan could not be saved: %s", err)

    return JSONResponse({**result, "model": MODEL_ID})


@app.post("/api/search")
async def search(req: SearchRequest):
    job_description = (req.jobDescription or "").strip()

    if len(job_description) < 20:
        return JSONResponse({"error": "Job description must be at least 20 characters"}, status_code=400)
    if not config.APIFY_API_KEY:
        return JSONResponse({"error": "APIFY_API_KEY not found in .env"}, status_code=500)
    if req.useAi and not config.OPENROUTER_API_KEY:
        return JSONResponse({"error": "OPENROUTER_API_KEY not found in .env"}, status_code=500)

    capped_limit = min(config.MAX_LIMIT, max(config.MIN_LIMIT, req.limit))

    # NDJSON stream: har line ek event, taaki UI live progress dikha sake.
    return StreamingResponse(
        _search_stream(req, job_description, capped_limit),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _search_stream(req: SearchRequest, job_description: str, limit: int) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()
    search_id: int | None = None
    finished = False

    async def send(event: dict) -> None:
        await queue.put(event)

    async def progress(stage: str, message: str, is_error: bool = False) -> None:
        await send({"type": "progress", "stage": stage, "message": message, "isError": is_error})

    async def pipeline() -> None:
        nonlocal search_id, finished
        try:
            # Row pehle ban jaati hai taaki adhoori/fail hui runs bhi dikh sakein.
            try:
                search_id = await store.start_search(
                    job_description=job_description,
                    limit=limit,
                    source=req.source,
                    use_ai=req.useAi,
                    model=MODEL_ID if req.useAi else None,
                )
            except Exception as err:
                log.warning("search row could not be created: %s", err)

            await send({"type": "search", "searchId": search_id, "cost": store.estimate_cost(limit, req.source)})

            params = {"title": None, "location": "India", "country": "IN", "summary": "", "mustHaveSkills": []}

            override = (req.titleOverride or "").strip()

            if req.useAi:
                await progress("parse", f"{MODEL_ID} is reading the job description...")
                extracted = await extract_search_params(job_description, config.OPENROUTER_API_KEY)
                params = extracted["params"]
            else:
                # AI off ho to JD ki pehli line ko hi search keyword maan lete hain.
                params["title"] = job_description.split("\n")[0].strip()[:60]

            # User ka apna title hamesha jeetta hai — model ka guess uske upar
            # nahi chadhta. Location aur skills waise hi rehte hain.
            if override:
                params["title"] = override[:80]

            await progress("parse", f"Search built: \"{params['title']}\" in {params['location']} ({params['country']})")

            await send({"type": "params", "params": params, "limit": limit})

            await progress("scrape", f"Apify is running (max {limit} jobs per source)...")
            jobs = await scrape_jobs(
                title=params["title"],
                location=params["location"],
                country=params["country"],
                limit=limit,
                source=req.source,
                token=config.APIFY_API_KEY,
                on_progress=progress,
            )
            await progress("scrape", f"Found {len(jobs)} unique jobs in total")

            # Scoring me ~30s lagte hain. Table ko tab tak khaali rakhne ke bajaye
            # unscored jobs turant bhej dete hain — UI bharti hai, scores baad me aate hain.
            if req.useAi and jobs:
                await send({"type": "partial", "jobs": jobs, "params": params})

            usage = None
            if req.useAi and jobs:
                await progress("score", f"Matching {len(jobs)} jobs against the JD...")
                scored = await score_jobs(
                    job_description,
                    jobs,
                    config.OPENROUTER_API_KEY,
                    batch_size=req.batchSize,
                    on_progress=progress,
                )
                jobs = scored["jobs"]
                usage = scored["usage"]
                # Best match sabse upar.
                jobs.sort(key=lambda j: j["matchScore"] if j.get("matchScore") is not None else -1, reverse=True)

            try:
                await store.finish_search(search_id, jobs=jobs, params=params, usage=usage)
                finished = True
            except Exception as err:
                log.warning("search %s could not be saved: %s", search_id, err)

            await send({
                "type": "done",
                "searchId": search_id,
                "jobs": jobs,
                "params": params,
                "usage": usage,
                "model": MODEL_ID,
            })
        except asyncio.CancelledError:
            raise
        except Exception as err:
            await store.fail_search(search_id, str(err))
            finished = True
            await send({"type": "error", "message": str(err)})
        finally:
            await queue.put(None)

    task = asyncio.create_task(pipeline())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield json.dumps(event, default=str) + "\n"
    finally:
        # Browser tab band ho jaye to background kaam bhi rok do — aur adhoori
        # row ko 'running' me sadne mat do.
        if not task.done():
            task.cancel()
        if not finished and search_id:
            # Yahan await nahi kar sakte — generator khud cancel ho raha hota hai.
            # Alag task chhod dete hain taaki row 'running' me na latki rahe.
            _background(store.fail_search(search_id, "Search was stopped before it finished", status="cancelled"))


# create_task ka reference rakhna zaroori hai, warna GC beech me utha leta hai.
_tasks: set[asyncio.Task] = set()


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ─────────────────────────── reach out ───────────────────────────

@app.post("/api/outreach")
async def outreach_draft(req: OutreachRequest) -> JSONResponse:
    """Ek posting ke liye reach-out draft — chhoti company me founder, badi me HR."""
    profile = (req.profile or "").strip()

    if not req.job or not (req.job.get("title") or req.job.get("company")):
        return JSONResponse({"error": "No job supplied"}, status_code=400)
    if len(profile) < 20:
        return JSONResponse({"error": "Add your resume or profile first (at least 20 characters)"}, status_code=400)
    if not config.OPENROUTER_API_KEY:
        return JSONResponse({"error": "OPENROUTER_API_KEY not found in .env"}, status_code=500)

    try:
        result = await draft_outreach(req.job, profile, config.OPENROUTER_API_KEY,
                                      threshold=config.FOUNDER_MAX_EMPLOYEES)
    except Exception as err:
        return JSONResponse({"error": f"Could not draft the message: {err}"}, status_code=502)

    # Founder-ya-HR ka faisla model ka nahi, hamara rule hai.
    draft = outreach.finalize(result["draft"], req.job)

    try:
        await store.save_outreach(
            search_id=req.searchId,
            job_key=store.job_key(req.job),
            draft=draft,
            usage=result.get("usage"),
            model=MODEL_ID,
        )
    except Exception as err:
        log.warning("outreach draft could not be saved: %s", err)

    return JSONResponse({"draft": draft, "key": store.job_key(req.job), "model": MODEL_ID})


@app.get("/api/outreach")
async def outreach_for_search(searchId: int) -> JSONResponse:
    """Purani search kholne par uske saare drafts wapas."""
    return JSONResponse({"drafts": await store.list_outreach(searchId)})


# ─────────────────────────── history (DB) ───────────────────────────

@app.get("/api/searches")
async def list_searches(limit: int = 25, all: bool = False) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"searches": [], "db": db.status()})
    rows = await store.list_searches(limit=max(1, min(100, limit)), include_all=all)
    return JSONResponse({"searches": rows, "db": db.status()})


@app.get("/api/searches/{search_id}")
async def get_search(search_id: int) -> JSONResponse:
    row = await store.get_search(search_id)
    if not row:
        return JSONResponse({"error": "Search not found"}, status_code=404)
    return JSONResponse(row)


@app.delete("/api/searches/{search_id}")
async def delete_search(search_id: int) -> JSONResponse:
    deleted = await store.delete_search(search_id)
    if not deleted:
        return JSONResponse({"error": "Search not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": deleted})


@app.delete("/api/searches")
async def clear_searches() -> JSONResponse:
    return JSONResponse({"ok": True, "deleted": await store.clear_searches()})


# ─────────────────────────── shortlist (DB) ───────────────────────────

@app.get("/api/saved")
async def list_saved() -> JSONResponse:
    return JSONResponse({"saved": await store.list_saved()})


@app.post("/api/saved")
async def add_saved(req: SaveRequest) -> JSONResponse:
    if not req.job:
        return JSONResponse({"error": "No job supplied"}, status_code=400)
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — shortlist cannot be saved"}, status_code=503)
    try:
        job = await store.add_saved(req.job, req.searchId)
    except Exception as err:
        # Sabse aam wajah: searchId ki row beech me delete ho gayi.
        log.warning("could not save job: %s", err)
        try:
            job = await store.add_saved(req.job, None)
        except Exception as retry_err:
            return JSONResponse({"error": f"Could not save this job: {retry_err}"}, status_code=500)
    return JSONResponse({"ok": True, "job": job, "key": store.job_key(req.job)})


@app.delete("/api/saved")
async def remove_saved(key: str) -> JSONResponse:
    return JSONResponse({"ok": True, "deleted": await store.remove_saved(key)})


# ─────────────────────────── overview + import ───────────────────────────

@app.get("/api/stats")
async def stats() -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"searches": 0, "roles": 0, "spend": 0.0, "avgScore": None, "saved": 0, "db": db.status()})
    return JSONResponse({**await store.stats(), "db": db.status()})


@app.post("/api/import")
async def import_legacy(req: ImportRequest) -> JSONResponse:
    """Browser me pade purane searches/saved jobs ko ek baar DB me le aata hai."""
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected"}, status_code=503)
    result = await store.import_legacy(req.searches, req.saved)
    return JSONResponse({"ok": True, **result})


# Frontend sabse aakhir me mount hota hai taaki /api/* routes pehle match hon.
app.mount("/", StaticFiles(directory=str(config.PUBLIC_DIR), html=True), name="static")

# Password set ho to poori app (API + frontend) uske peeche chali jaati hai.
if config.APP_PASSWORD:
    app.add_middleware(BasicAuth, username=config.APP_USERNAME, password=config.APP_PASSWORD)
    log.info("password gate on (user: %s)", config.APP_USERNAME)
else:
    log.warning("APP_PASSWORD not set — app is open to anyone who has the URL")
