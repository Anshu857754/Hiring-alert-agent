"""FastAPI backend — search stream, PDF extract, Postgres persistence, aur static frontend."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, connect, crypto, db, docs, mailer, outreach, store, users
from . import people as people_mod
from .apify import scrape_jobs
from .llm import MODEL_ID, build_learning_plan, draft_outreach, extract_search_params, score_jobs

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("hiring-agent")

# Ye do baar-baar chahiye hote hain — ek hi jagah likhe taaki wording na bhatke.
APIFY_MISSING = "Add your Apify API key in Settings before running this"
OPENROUTER_MISSING = "Add your OpenRouter API key in Settings before running this"


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
        gone = await users.purge_expired_sessions()
        if gone:
            log.info("%s expired session(s) removed", gone)
        dead_links = await users.purge_expired_resets()
        if dead_links:
            log.info("%s used/expired password reset link(s) removed", dead_links)
        log.info("database ready (schema: %s)", config.DB_SCHEMA)

    # Ek hi jagah: kya-kya set nahi hai aur uska kya asar padega. Host par
    # deploy karke "kaam kyun nahi kar raha" dhoondhne se behtar hai.
    missing = []
    if not crypto.ready():
        missing.append("APP_SECRET_KEY / DATABASE_URL — users API keys/cookies save NAHI kar payenge")
    elif crypto.derived_only():
        missing.append("APP_SECRET_KEY — abhi DATABASE_URL se derive ho rahi hai (chalta hai, "
                       "par alag se set karna behtar hai)")
    if not mailer.configured():
        missing.append("BREVO_API_KEY / RESEND_API_KEY / SMTP_* — reset link sirf is log me "
                       "aayega, email nahi jaayegi")
    if not config.COOKIE_SECURE:
        missing.append("COOKIE_SECURE=1 — https deploy par set karo")
    if missing:
        log.warning("missing config (%s):", len(missing))
        for item in missing:
            log.warning("  - %s", item)
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


# ─────────────────────────── accounts ───────────────────────────
# Har banda apna account banata hai aur apni API keys deta hai. Server ki
# .env wali keys kisi aur user ko nahi milti — warna pehla ajnabi hi baaki
# sabke Apify credits jala deta.


class SignupRequest(BaseModel):
    email: str = ""
    password: str = ""
    name: str | None = None


class LoginRequest(BaseModel):
    email: str = ""
    password: str = ""


class PasswordRequest(BaseModel):
    current: str = ""
    new: str = ""


class ForgotRequest(BaseModel):
    email: str = ""


class ResetRequest(BaseModel):
    token: str = ""
    password: str = ""


class KeysRequest(BaseModel):
    # None = jaisi hai waisi rehne do. "" = hata do.
    apify: str | None = None
    openRouter: str | None = None


def _session_response(payload: dict, token: str, expires) -> JSONResponse:
    res = JSONResponse(payload)
    # httponly: JS cookie ko chhu bhi nahi sakta, isliye XSS se session nahi
    # churaya ja sakta. samesite=lax: normal navigation par cookie jaati hai
    # par cross-site POST par nahi.
    res.set_cookie(
        users.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        max_age=users.SESSION_DAYS * 24 * 3600,
        expires=expires,
        path="/",
    )
    return res


async def current_user(request: Request) -> dict:
    """Har protected route ka pehla darwaza."""
    if not db.enabled():
        raise HTTPException(status_code=503, detail="Database is not connected — accounts are unavailable")
    user = await users.user_for_session(request.cookies.get(users.SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


async def user_keys(user: dict) -> dict:
    """Us user ki apni keys. Set nahi hain to None — caller saaf error deta hai."""
    return await users.get_keys(user["id"])


DEMO_READ_ONLY = (
    "This is the public demo, so it stays read-only — the saved run is the same for everyone. "
    "Create a free account and add your own Apify and OpenRouter keys to run this for real."
)


async def writable_user(user: dict = Depends(current_user)) -> dict:
    """Har wo route jo paisa kharch kare ya data badle, isse hoke jaata hai.

    Demo account ko yahin rok dete hain — frontend par buttons disable karna
    kaafi nahi hai, koi bhi seedha API hit kar ke Apify credits jala sakta
    tha, ya sabke liye rakha demo data delete kar sakta tha.
    """
    if user.get("isDemo"):
        raise HTTPException(status_code=403, detail=DEMO_READ_ONLY)
    return user


@app.post("/api/auth/signup")
async def signup(req: SignupRequest, request: Request) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — accounts cannot be created"}, status_code=503)
    try:
        user = await users.create_user(req.email, req.password, req.name)
    except users.AuthError as err:
        # code frontend ke liye — "email pehle se hai" par wo alag callout aur
        # "Sign in instead" button dikhata hai.
        return JSONResponse({"error": str(err), "code": err.code}, status_code=400)
    except Exception as err:
        log.exception("signup failed")
        return JSONResponse({"error": f"Could not create the account: {err}"}, status_code=500)

    token, expires = await users.start_session(user["id"], request.headers.get("user-agent"))
    return _session_response({"ok": True, "user": user}, token, expires)


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — sign-in is unavailable"}, status_code=503)
    try:
        user = await users.authenticate(req.email, req.password)
    except users.AuthError as err:
        return JSONResponse({"error": str(err)}, status_code=401)

    token, expires = await users.start_session(user["id"], request.headers.get("user-agent"))
    return _session_response({"ok": True, "user": user}, token, expires)


@app.post("/api/auth/demo")
async def demo_login(request: Request) -> JSONResponse:
    """Bina signup ke demo account me ghusao — LinkedIn se aaya banda seedha
    andar dekhe, form bharne me na atke.

    Account read-only hai: har paisa kharch karne wala aur har delete wala
    route `writable_user` par 403 deta hai.
    """
    if not config.DEMO_ENABLED:
        return JSONResponse({"error": "The demo is turned off on this server"}, status_code=404)
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — the demo is unavailable"}, status_code=503)

    user = await users.ensure_demo_user()
    if not user:
        return JSONResponse({"error": "Could not open the demo account"}, status_code=500)

    token, expires = await users.start_session(user["id"], request.headers.get("user-agent"))
    return _session_response({"ok": True, "user": user}, token, expires)


@app.post("/api/auth/logout")
async def logout(request: Request) -> JSONResponse:
    await users.end_session(request.cookies.get(users.SESSION_COOKIE))
    res = JSONResponse({"ok": True})
    res.delete_cookie(users.SESSION_COOKIE, path="/")
    return res


@app.get("/api/auth/me")
async def whoami(request: Request) -> JSONResponse:
    """Frontend boot par yahi poochta hai — 401 matlab login screen dikhao."""
    if not db.enabled():
        return JSONResponse({"user": None, "db": db.status()})
    user = await users.user_for_session(request.cookies.get(users.SESSION_COOKIE))
    if not user:
        return JSONResponse({"user": None, "db": db.status()})
    return JSONResponse({"user": user, "db": db.status()})


@app.post("/api/auth/password")
async def update_password(req: PasswordRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    try:
        await users.change_password(user["id"], req.current, req.new)
    except users.AuthError as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    # Sab sessions gir chuke — apni cookie bhi saaf kar dete hain.
    res = JSONResponse({"ok": True, "message": "Password changed — sign in again"})
    res.delete_cookie(users.SESSION_COOKIE, path="/")
    return res


# ── forgot password ──────────────────────────────────────────────
# Teen baatein poore flow me chalti hain:
#   1. Jawab hamesha ek jaisa — "agar account hai to link bhej diya". Warna ye
#      route email checker ban jaata: 200 matlab registered, 404 matlab nahi.
#   2. Raw token sirf email me jaata hai, response me kabhi nahi. SMTP set na
#      ho to link server log me milta hai — browser me dikhana matlab koi bhi
#      kisi ka bhi password badal le.
#   3. Ek email par har RESET_COOLDOWN_SECONDS me ek hi mail, taaki koi kisi
#      ke inbox par button daba ke 500 mails na girwa de.

RESET_OK = "If that email has an account, a reset link is on its way. Check your inbox and spam."
RESET_COOLDOWN_SECONDS = 60
_reset_sent_at: dict[str, float] = {}


def _reset_throttled(email: str) -> bool:
    now = time.monotonic()
    last = _reset_sent_at.get(email)
    if last is not None and now - last < RESET_COOLDOWN_SECONDS:
        return True
    _reset_sent_at[email] = now
    # Dictionary ko chhota rakho — ye process ki memory me hai, DB me nahi.
    if len(_reset_sent_at) > 500:
        for stale in [k for k, t in _reset_sent_at.items() if now - t > RESET_COOLDOWN_SECONDS]:
            _reset_sent_at.pop(stale, None)
    return False


@app.post("/api/auth/forgot")
async def forgot_password(req: ForgotRequest, request: Request) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — password reset is unavailable"}, status_code=503)

    email = (req.email or "").strip().lower()
    if not email:
        return JSONResponse({"error": "Enter your email address"}, status_code=400)

    if _reset_throttled(email):
        log.info("reset request for %s throttled", email)
        return JSONResponse({"ok": True, "message": RESET_OK})

    made = await users.create_reset_token(email, request.client.host if request.client else None)
    if made:
        user, token = made
        link = f"{config.APP_BASE_URL}/?reset={token}"
        await mailer.send_password_reset(user["email"], user["name"], link)

    # Email mile ya na mile, jawab wahi. Bhejne me dikkat aayi to bhi wahi —
    # mailer ne link log me likh diya hai.
    return JSONResponse({"ok": True, "message": RESET_OK, "emailConfigured": mailer.configured()})


@app.get("/api/auth/reset")
async def check_reset(token: str = "") -> JSONResponse:
    """Reset form dikhane se pehle frontend link ko yahan verify karta hai."""
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected"}, status_code=503)
    try:
        info = await users.check_reset_token(token)
    except users.AuthError as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    return JSONResponse({"ok": True, **info})


@app.post("/api/auth/reset")
async def do_reset(req: ResetRequest) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected"}, status_code=503)
    try:
        done = await users.reset_password(req.token, req.password)
    except users.AuthError as err:
        return JSONResponse({"error": str(err)}, status_code=400)

    # Jaan-boojh kar login nahi karate — naya password ek baar type karwana
    # hi confirm karta hai ki wo yaad hai.
    res = JSONResponse({"ok": True, "email": done["email"], "message": "Password changed — sign in with it now"})
    res.delete_cookie(users.SESSION_COOKIE, path="/")
    return res


@app.post("/api/auth/keys")
async def save_api_keys(req: KeysRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    if (req.apify or req.openRouter) and not crypto.ready():
        return JSONResponse(
            {"error": "APP_SECRET_KEY is not set on the server, so API keys cannot be encrypted. "
                      "Ask the admin to set it in .env."},
            status_code=400,
        )
    try:
        updated = await users.save_keys(user["id"], apify=req.apify, openrouter=req.openRouter)
    except Exception as err:
        return JSONResponse({"error": f"Could not save the keys: {err}"}, status_code=500)
    return JSONResponse({"ok": True, "user": updated})


@app.get("/api/health")
async def health() -> dict:
    """Public — login screen ko bhi chahiye. Yahan kisi user ka data nahi jaata."""
    return {
        "ok": True,
        "model": MODEL_ID,
        # Keys ab har user ki apni hoti hain; ye sirf batata hai ki server par
        # cookie/keys encrypt karne ka intezaam hai ya nahi.
        "secretReady": crypto.ready(),
        "db": db.status(),
        # Deploy debug karne ke liye. Sirf "set hai ya nahi" — koi value yahan
        # se bahar nahi jaati. Iske bina har baar guess karna padta tha ki
        # host par kaunsi variable reh gayi.
        "env": {
            "APP_SECRET_KEY": crypto.ready(),
            "APP_SECRET_KEY_derived": crypto.derived_only(),
            "EMAIL": mailer.provider() or False,
            "APP_BASE_URL": config.APP_BASE_URL,
            "COOKIE_SECURE": config.COOKIE_SECURE,
            "DEMO": config.DEMO_ENABLED,
        },
    }


@app.post("/api/extract")
async def extract(file: UploadFile = File(...), user: dict = Depends(current_user)) -> JSONResponse:
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
async def recommend(req: RecommendRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    """Scored postings ke gaps se 15/30 din ka upskilling plan banata hai."""
    profile = (req.profile or "").strip()

    if len(profile) < 20:
        return JSONResponse({"error": "Add your resume or profile first (at least 20 characters)"}, status_code=400)
    if not req.jobs:
        return JSONResponse({"error": "Run a search first — there are no postings to analyse"}, status_code=400)

    keys = await user_keys(user)
    if not keys["openrouter"]:
        return JSONResponse({"error": OPENROUTER_MISSING}, status_code=400)

    try:
        result = await build_learning_plan(profile, req.jobs, keys["openrouter"])
    except Exception as err:
        return JSONResponse({"error": f"Could not build a plan: {err}"}, status_code=502)

    # Plan bhi search ke saath DB me rehta hai — history kholte hi wapas mil jaata hai.
    try:
        await store.save_plan(
            user_id=user["id"],
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
async def search(req: SearchRequest, user: dict = Depends(writable_user)):
    job_description = (req.jobDescription or "").strip()

    if len(job_description) < 20:
        return JSONResponse({"error": "Job description must be at least 20 characters"}, status_code=400)

    keys = await user_keys(user)
    if not keys["apify"]:
        return JSONResponse({"error": APIFY_MISSING}, status_code=400)
    if req.useAi and not keys["openrouter"]:
        return JSONResponse({"error": OPENROUTER_MISSING}, status_code=400)

    capped_limit = min(config.MAX_LIMIT, max(config.MIN_LIMIT, req.limit))

    # NDJSON stream: har line ek event, taaki UI live progress dikha sake.
    return StreamingResponse(
        _search_stream(req, job_description, capped_limit, user, keys),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _search_stream(req: SearchRequest, job_description: str, limit: int,
                         user: dict, keys: dict) -> AsyncIterator[str]:
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
                    user_id=user["id"],
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
                extracted = await extract_search_params(job_description, keys["openrouter"])
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
                token=keys["apify"],
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
                    keys["openrouter"],
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
async def outreach_draft(req: OutreachRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    """Ek posting ke liye reach-out draft — chhoti company me founder, badi me HR."""
    profile = (req.profile or "").strip()

    if not req.job or not (req.job.get("title") or req.job.get("company")):
        return JSONResponse({"error": "No job supplied"}, status_code=400)
    if len(profile) < 20:
        return JSONResponse({"error": "Add your resume or profile first (at least 20 characters)"}, status_code=400)

    keys = await user_keys(user)
    if not keys["openrouter"]:
        return JSONResponse({"error": OPENROUTER_MISSING}, status_code=400)

    try:
        result = await draft_outreach(req.job, profile, keys["openrouter"],
                                      threshold=config.FOUNDER_MAX_EMPLOYEES)
    except Exception as err:
        return JSONResponse({"error": f"Could not draft the message: {err}"}, status_code=502)

    # Founder-ya-HR ka faisla model ka nahi, hamara rule hai.
    draft = outreach.finalize(result["draft"], req.job)

    try:
        await store.save_outreach(
            user_id=user["id"],
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
async def outreach_for_search(searchId: int, user: dict = Depends(current_user)) -> JSONResponse:
    """Purani search kholne par uske saare drafts wapas."""
    return JSONResponse({"drafts": await store.list_outreach(searchId, user["id"])})


# ─────────────────────────── history (DB) ───────────────────────────

@app.get("/api/searches")
async def list_searches(limit: int = 25, all: bool = False,
                        user: dict = Depends(current_user)) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"searches": [], "db": db.status()})
    rows = await store.list_searches(user["id"], limit=max(1, min(100, limit)), include_all=all)
    return JSONResponse({"searches": rows, "db": db.status()})


@app.get("/api/searches/{search_id}")
async def get_search(search_id: int, user: dict = Depends(current_user)) -> JSONResponse:
    row = await store.get_search(search_id, user["id"])
    if not row:
        return JSONResponse({"error": "Search not found"}, status_code=404)
    return JSONResponse(row)


@app.delete("/api/searches/{search_id}")
async def delete_search(search_id: int, user: dict = Depends(writable_user)) -> JSONResponse:
    deleted = await store.delete_search(search_id, user["id"])
    if not deleted:
        return JSONResponse({"error": "Search not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": deleted})


@app.delete("/api/searches")
async def clear_searches(user: dict = Depends(writable_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "deleted": await store.clear_searches(user["id"])})


# ─────────────────────────── shortlist (DB) ───────────────────────────

@app.get("/api/saved")
async def list_saved(user: dict = Depends(current_user)) -> JSONResponse:
    return JSONResponse({"saved": await store.list_saved(user["id"])})


@app.post("/api/saved")
async def add_saved(req: SaveRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    if not req.job:
        return JSONResponse({"error": "No job supplied"}, status_code=400)
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — shortlist cannot be saved"}, status_code=503)
    try:
        job = await store.add_saved(req.job, req.searchId, user_id=user["id"])
    except Exception as err:
        # Sabse aam wajah: searchId ki row beech me delete ho gayi.
        log.warning("could not save job: %s", err)
        try:
            job = await store.add_saved(req.job, None, user_id=user["id"])
        except Exception as retry_err:
            return JSONResponse({"error": f"Could not save this job: {retry_err}"}, status_code=500)
    return JSONResponse({"ok": True, "job": job, "key": store.job_key(req.job)})


@app.delete("/api/saved")
async def remove_saved(key: str, user: dict = Depends(writable_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "deleted": await store.remove_saved(key, user["id"])})


# ─────────────────────────── overview + import ───────────────────────────

@app.get("/api/stats")
async def stats(user: dict = Depends(current_user)) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"searches": 0, "roles": 0, "spend": 0.0, "avgScore": None, "saved": 0, "db": db.status()})
    return JSONResponse({**await store.stats(user["id"]), "db": db.status()})


@app.post("/api/import")
async def import_legacy(req: ImportRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    """Browser me pade purane searches/saved jobs ko ek baar DB me le aata hai."""
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected"}, status_code=503)
    result = await store.import_legacy(req.searches, req.saved, user_id=user["id"])
    return JSONResponse({"ok": True, **result})


# ─────────────────── sender accounts (LinkedIn se bhejne wala) ───────────────────
# Cookie yahan aati hai aur yahin ruk jaati hai — response me kabhi wapas nahi
# jaati. UI sirf hasCookie/status dekhta hai.

class SenderRequest(BaseModel):
    id: int | None = None
    label: str = "My LinkedIn"
    # Khaali chhod do to purani cookie waise hi rehti hai.
    liAt: str | None = None
    jsessionid: str | None = None
    userAgent: str | None = None
    isPremium: bool = False
    provider: Literal["apify", "unipile"] = "apify"


class DiscoverRequest(BaseModel):
    job: dict = Field(default_factory=dict)
    # 'founder' ya 'hr'. Na do to employees se rule khud tay karta hai.
    target: str | None = None
    employees: int | None = None
    location: str | None = None
    limit: int = Field(default=10, ge=1, le=25)
    searchId: int | None = None


class SendRequest(BaseModel):
    contactIds: list[int] = Field(default_factory=list)
    # contactId -> note. Jo yahan na ho uske liye draft ka note use hota hai.
    notes: dict[str, str] = Field(default_factory=dict)
    senderId: int | None = None


@app.get("/api/senders")
async def list_senders(user: dict = Depends(current_user)) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"senders": [], "secretReady": crypto.ready(), "db": db.status()})
    return JSONResponse({
        "senders": await store.list_senders(user["id"]),
        "secretReady": crypto.ready(),
        "provider": config.CONNECT_PROVIDER,
        "db": db.status(),
    })


@app.post("/api/senders")
async def save_sender(req: SenderRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — the sender account cannot be stored"}, status_code=503)

    label = (req.label or "").strip() or "My LinkedIn"
    li_at = (req.liAt or "").strip() or None

    # Nayi cookie aa rahi hai to encryption key honi hi chahiye. Bina uske
    # save karna matlab plain text — wo hum nahi karte.
    if li_at and not crypto.ready():
        return JSONResponse(
            {"error": "APP_SECRET_KEY is not set in .env — it is required before a LinkedIn cookie can be stored. "
                      "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""},
            status_code=400,
        )
    if not req.id and not li_at:
        return JSONResponse({"error": "Paste your li_at cookie to add a sender account"}, status_code=400)

    try:
        sender = await store.save_sender(
            user_id=user["id"],
            sender_id=req.id,
            label=label,
            li_at=li_at,
            jsessionid=(req.jsessionid or "").strip() or None,
            user_agent=(req.userAgent or "").strip() or None,
            is_premium=req.isPremium,
            provider=req.provider,
        )
    except crypto.SecretMissing as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    except Exception as err:
        return JSONResponse({"error": f"Could not save the account: {err}"}, status_code=500)

    if not sender:
        return JSONResponse({"error": "Sender account not found"}, status_code=404)
    return JSONResponse({"ok": True, "sender": sender})


@app.post("/api/senders/{sender_id}/verify")
async def verify_sender(sender_id: int, user: dict = Depends(writable_user)) -> JSONResponse:
    """Ek GET se dekhta hai ki cookie zinda hai — koi invite nahi jaata."""
    secrets_row = await store.sender_secrets(sender_id, user["id"])
    if not secrets_row:
        return JSONResponse({"error": "Sender account not found"}, status_code=404)

    if secrets_row.get("provider") == "unipile":
        status, detail = ("ready", "Unipile handles the session for this account")
    elif not secrets_row.get("li_at"):
        status, detail = (
            "unverified",
            "No usable cookie — if APP_SECRET_KEY changed, paste the li_at cookie again",
        )
    else:
        status, detail = await connect.verify_cookie(secrets_row["li_at"], secrets_row.get("userAgent"))

    sender = await store.mark_sender_status(sender_id, status, detail)
    return JSONResponse({"ok": True, "sender": sender, "status": status, "detail": detail})


@app.post("/api/senders/{sender_id}/default")
async def make_default_sender(sender_id: int, user: dict = Depends(writable_user)) -> JSONResponse:
    await store.set_default_sender(sender_id, user["id"])
    return JSONResponse({"ok": True, "senders": await store.list_senders(user["id"])})


@app.delete("/api/senders/{sender_id}")
async def remove_sender(sender_id: int, user: dict = Depends(writable_user)) -> JSONResponse:
    deleted = await store.delete_sender(sender_id, user["id"])
    if not deleted:
        return JSONResponse({"error": "Sender account not found"}, status_code=404)
    return JSONResponse({"ok": True, "deleted": deleted})


# ─────────────────────────── decision makers ───────────────────────────

@app.get("/api/contacts")
async def list_contacts(jobKey: str | None = None, limit: int = 200,
                        user: dict = Depends(current_user)) -> JSONResponse:
    if not db.enabled():
        return JSONResponse({"contacts": []})
    return JSONResponse(
        {"contacts": await store.list_contacts(user["id"], jobKey, max(1, min(500, limit)))}
    )


@app.post("/api/contacts/discover")
async def discover_contacts(req: DiscoverRequest, user: dict = Depends(writable_user)) -> JSONResponse:
    """Ek company ke decision makers Apify se — cookie ki zaroorat nahi."""
    company = (req.job.get("company") or "").strip()

    if not company:
        return JSONResponse({"error": "This posting has no company name to search on"}, status_code=400)

    keys = await user_keys(user)
    if not keys["apify"]:
        return JSONResponse({"error": APIFY_MISSING}, status_code=400)

    # Target diya ho to wahi; warna wahi rule jo draft me chalta hai.
    target = req.target if req.target in (outreach.FOUNDER, outreach.HR) else None
    if not target:
        target, _ = outreach.decide_target(req.employees, "high" if req.employees else "low")

    try:
        people = await people_mod.find_decision_makers(
            company=company,
            target=target,
            location=req.location or req.job.get("location"),
            limit=req.limit,
            token=keys["apify"],
        )
    except Exception as err:
        return JSONResponse({"error": f"Could not find people at {company}: {err}"}, status_code=502)

    if not people:
        return JSONResponse({
            "contacts": [],
            "target": target,
            "message": f"No public {'founder/CTO' if target == outreach.FOUNDER else 'HR'} profile could be "
                       f"confirmed at {company}. Profiles that do not actually list this company are dropped "
                       f"rather than shown, so you never message the wrong person.",
        })

    try:
        saved = await store.save_contacts(
            people, user_id=user["id"], job_key=store.job_key(req.job),
            search_id=req.searchId, employees=req.employees,
        )
    except Exception as err:
        log.warning("contacts could not be saved: %s", err)
        saved = people   # DB down — table phir bhi bhar do, bas persist nahi hoga

    return JSONResponse({"contacts": saved, "target": target, "company": company})


@app.delete("/api/contacts/{contact_id}")
async def remove_contact(contact_id: int, user: dict = Depends(writable_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "deleted": await store.delete_contact(contact_id, user["id"])})


# ─────────────────────────── connection requests ───────────────────────────

@app.post("/api/connect/send")
async def send_connections(req: SendRequest, user: dict = Depends(writable_user)):
    """Chune hue logon ko connection request + note.

    Stream isliye hai ki har invite ke beech ~25s ka gap hai: 7 log matlab
    do-teen minute. Bina live update ke UI mara hua lagta.
    """
    if not req.contactIds:
        return JSONResponse({"error": "Select at least one person"}, status_code=400)
    if not db.enabled():
        return JSONResponse({"error": "Database is not connected — sending is disabled"}, status_code=503)

    if len(req.contactIds) > config.MAX_BATCH_INVITES:
        return JSONResponse(
            {"error": f"Send at most {config.MAX_BATCH_INVITES} at a time — LinkedIn flags bursts"},
            status_code=400,
        )

    keys = await user_keys(user)
    if not keys["apify"] and config.CONNECT_PROVIDER != "unipile":
        return JSONResponse({"error": APIFY_MISSING}, status_code=400)

    sender = await store.sender_secrets(req.senderId, user["id"])
    if not sender:
        return JSONResponse({"error": "Add a LinkedIn sender account in Settings first"}, status_code=400)
    if sender.get("provider") != "unipile" and not sender.get("li_at"):
        return JSONResponse(
            {"error": "This sender has no usable cookie — open Settings and paste the li_at cookie again"},
            status_code=400,
        )

    # Quota check bhejne se pehle. Counters ko aaj/is hafte par le aata hai.
    quota = await store.roll_quota(sender["id"]) or sender
    daily_left = max(0, (quota.get("dailyCap") or config.DAILY_INVITE_CAP) - (quota.get("sentToday") or 0))
    weekly_left = max(0, (quota.get("weeklyCap") or config.WEEKLY_INVITE_CAP) - (quota.get("sentThisWeek") or 0))
    allowance = min(daily_left, weekly_left)

    if allowance <= 0:
        return JSONResponse(
            {"error": f"Invite limit reached for this account ({quota.get('sentToday')} today, "
                      f"{quota.get('sentThisWeek')} this week). Try again tomorrow."},
            status_code=429,
        )

    return StreamingResponse(
        _connect_stream(req, sender, allowance, user, keys),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _connect_stream(req: SendRequest, sender: dict, allowance: int,
                          user: dict, keys: dict) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()

    async def send(event: dict) -> None:
        await queue.put(event)

    async def pipeline() -> None:
        sent_count = 0
        try:
            contacts = await store.contacts_by_ids(req.contactIds, user["id"])
            by_id = {c["id"]: c for c in contacts}

            # Jinko pehle bheja ja chuka unhe chup-chaap chhod dete hain —
            # dobara invite bhejna LinkedIn par sabse tez restriction laata hai.
            done = await store.already_requested(req.contactIds, user["id"])

            targets: list[dict] = []
            for contact_id in req.contactIds:
                contact = by_id.get(contact_id)
                if not contact:
                    continue
                if contact_id in done:
                    await send({"type": "skipped", "contactId": contact_id,
                                "name": contact["fullName"], "reason": "Already invited"})
                    continue
                targets.append({
                    "contactId": contact_id,
                    "profileUrl": contact["profileUrl"],
                    "fullName": contact["fullName"],
                    "note": req.notes.get(str(contact_id)) or "",
                })

            # Quota se zyada select ho gaya ho to baaki agle din ke liye chhod do.
            if len(targets) > allowance:
                for extra in targets[allowance:]:
                    await send({"type": "skipped", "contactId": extra["contactId"],
                                "name": extra["fullName"],
                                "reason": f"Daily/weekly limit — only {allowance} left on this account"})
                targets = targets[:allowance]

            if not targets:
                await send({"type": "done", "sent": 0, "failed": 0, "results": []})
                return

            await send({"type": "start", "count": len(targets),
                        "noteLimit": connect.note_limit(bool(sender.get("isPremium")))})

            async def progress(**event) -> None:
                await send(event)

            results = await connect.send_batch(
                targets=targets, sender=sender, apify_token=keys["apify"], on_progress=progress
            )

            sent_count = sum(1 for r in results if r["status"] == "sent")

            for result in results:
                try:
                    await store.record_request(
                        contact_id=result["contactId"],
                        sender_id=sender["id"],
                        provider=sender.get("provider") or config.CONNECT_PROVIDER,
                        note=result.get("note") or "",
                        status=result["status"],
                        error=result.get("error"),
                        run_url=result.get("runUrl"),
                    )
                except Exception as err:
                    log.warning("request row could not be saved: %s", err)

            # Counter sirf sach me gaye invites par badhta hai.
            await store.bump_sent(sender["id"], sent_count)

            await send({
                "type": "done",
                "sent": sent_count,
                "failed": len(results) - sent_count,
                "results": results,
            })
        except asyncio.CancelledError:
            raise
        except Exception as err:
            log.exception("connect batch failed")
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
        # Tab band ho gaya — beech ka invite loop rok do. Jo ja chuke wo ja chuke.
        if not task.done():
            task.cancel()


# Frontend sabse aakhir me mount hota hai taaki /api/* routes pehle match hon.
app.mount("/", StaticFiles(directory=str(config.PUBLIC_DIR), html=True), name="static")

# Purana APP_PASSWORD wala Basic-auth gate hat gaya — ab har banda apna
# account banata hai (app/users.py) aur apni keys laata hai. Frontend bina
# login ke bhi serve hota hai, warna login screen hi na dikhti; asli darwaza
# har /api route par `Depends(current_user)` hai.
if not crypto.ready():
    log.warning("APP_SECRET_KEY not set — users will not be able to save API keys or cookies")
