"""FastAPI backend — search stream, PDF extract, aur static frontend."""
import asyncio
import json
from typing import AsyncIterator, Literal

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, docs
from .apify import scrape_jobs
from .llm import MODEL_ID, extract_search_params, score_jobs

app = FastAPI(title="Hiring Agent", version="2.0.0")


class SearchRequest(BaseModel):
    jobDescription: str = ""
    limit: int = config.MIN_LIMIT
    source: Literal["both", "linkedin", "indeed"] = "both"
    useAi: bool = True
    batchSize: int = Field(default=15, ge=5, le=30)


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "model": MODEL_ID,
        "apifyKey": bool(config.APIFY_API_KEY),
        "openRouterKey": bool(config.OPENROUTER_API_KEY),
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

    async def send(event: dict) -> None:
        await queue.put(event)

    async def progress(stage: str, message: str, is_error: bool = False) -> None:
        await send({"type": "progress", "stage": stage, "message": message, "isError": is_error})

    async def pipeline() -> None:
        try:
            params = {"title": None, "location": "India", "country": "IN", "summary": "", "mustHaveSkills": []}

            if req.useAi:
                await progress("parse", f"{MODEL_ID} is reading the job description...")
                extracted = await extract_search_params(job_description, config.OPENROUTER_API_KEY)
                params = extracted["params"]
                await progress("parse", f"Search built: \"{params['title']}\" in {params['location']} ({params['country']})")
            else:
                # AI off ho to JD ki pehli line ko hi search keyword maan lete hain.
                params["title"] = job_description.split("\n")[0].strip()[:60]
                await progress("parse", f"AI off — keyword: \"{params['title']}\"")

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

            await send({"type": "done", "jobs": jobs, "params": params, "usage": usage, "model": MODEL_ID})
        except asyncio.CancelledError:
            raise
        except Exception as err:
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
        # Browser tab band ho jaye to background kaam bhi rok do.
        if not task.done():
            task.cancel()


# Frontend sabse aakhir me mount hota hai taaki /api/* routes pehle match hon.
app.mount("/", StaticFiles(directory=str(config.PUBLIC_DIR), html=True), name="static")
