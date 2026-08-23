"""Connection request bhejne ka kaam — provider ke peeche chhupa hua.

Do wajah se interface banaya:

  1. LinkedIn ka koi official API nahi hai. Har raasta cookie par chalta hai
     aur har vendor apna shape maangta hai.
  2. Apify ke connect actors saste hain par bharose ke laayak kam (store par
     inke success rate 0-44% dikhte hain). Unipile paid hai aur chalta hai.
     Aaj Apify se kaam chalta hai, kal Unipile par switch karna sirf
     CONNECT_PROVIDER badalna hona chahiye — routes/UI ko farq na pade.

Rate limiting yahan hai, provider me nahi: LinkedIn ki limit account par
lagti hai, actor par nahi. Burst sabse aasaan detection signal hai, isliye
har invite ke beech gap daala jaata hai.
"""
import asyncio
import logging
import random
from typing import Any, Awaitable, Callable

import httpx
from apify_client import ApifyClientAsync

from . import config

log = logging.getLogger("hiring-agent.connect")

ProgressFn = Callable[..., Awaitable[None]]


class ConnectError(RuntimeError):
    """Bhejne me dikkat — message seedha UI par dikhta hai."""


def note_limit(is_premium: bool) -> int:
    return config.NOTE_LIMIT_PREMIUM if is_premium else config.NOTE_LIMIT_FREE


def trim_note(note: str | None, is_premium: bool) -> str:
    """Limit se bada note LinkedIn chup-chaap kaat deta hai — hum pehle kaat lete hain."""
    text = (note or "").strip()
    if not text:
        return ""
    cap = note_limit(is_premium)
    if len(text) <= cap:
        return text
    cut = text[: cap - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


# ─────────────────────────── providers ───────────────────────────

def _connect_input(actor: str, *, profile_url: str, note: str, cookies: dict) -> dict[str, Any]:
    """Har connect actor apne input keys maangta hai.

    Sabhi keys ek saath bhejna kaam nahi karta: jin actors ke input schema me
    `additionalProperties: false` hai wo poori run hi reject kar dete hain.
    Isliye mapping alag-alag rakhi hai — naya actor lagana ho to yahan ek
    branch jodo, baaki code haath na lagao.
    """
    li_at = cookies.get("li_at")

    if actor.startswith("data_link_miner/"):
        run_input: dict[str, Any] = {
            "action": "ADD",
            "profileUrls": [profile_url],
            "li_at": li_at,
            "message": note,
        }
    elif actor.startswith("addeus/"):
        run_input = {"liAtCookie": li_at, "profileUrl": profile_url, "message": note}
    elif actor.startswith("automationagents/"):
        run_input = {"li_at": li_at, "liProfileUrl": profile_url, "messageContent": {"message": note}}
    else:
        # Anjaan actor — sabse aam keys, aur error seedha user tak jaata hai.
        run_input = {"li_at": li_at, "profileUrl": profile_url, "message": note}

    if cookies.get("jsessionid"):
        run_input["JSESSIONID"] = cookies["jsessionid"]
    if cookies.get("user_agent"):
        run_input["User-Agent"] = cookies["user_agent"]
    return run_input


async def _send_via_apify(*, profile_url: str, note: str, cookies: dict, token: str) -> dict:
    """Apify connect actor. Actor ke input keys store page se aate hain."""
    if not token:
        raise ConnectError("Add your Apify API key in Settings before sending")

    actor_id = config.CONNECT_ACTOR
    run_input = _connect_input(actor_id, profile_url=profile_url, note=note, cookies=cookies)

    client = ApifyClientAsync(token=token)
    try:
        run = await client.actor(actor_id).call(run_input=run_input)
    except Exception as err:
        raise ConnectError(f"Apify actor {actor_id} could not be started: {err}") from err

    if run is None:
        raise ConnectError(f"Apify actor {actor_id} returned nothing")

    run_url = f"https://console.apify.com/actors/runs/{run.id}" if getattr(run, "id", None) else None

    if run.status != "SUCCEEDED":
        raise ConnectError(f"Apify run finished as {run.status} — check the run in the Apify console")

    # Kuch actors SUCCEEDED hote hain par dataset me per-profile failure likhte
    # hain. Us haal me "sent" bolna jhooth hoga.
    if run.default_dataset_id:
        page = await client.dataset(run.default_dataset_id).list_items()
        for item in page.items:
            failed = item.get("error") or item.get("failed") or item.get("errorMessage")
            if failed:
                raise ConnectError(str(failed))

    return {"runUrl": run_url}


async def _send_via_unipile(*, profile_url: str, note: str, account_id: str) -> dict:
    """Unipile hosted API — cookie unke paas rehti hai, hamare paas account id.

    Yahan cookie bilkul involve nahi hoti, isliye ye raasta zyada safe bhi hai
    aur zyada bharosemand bhi. Bas paid hai.
    """
    if not config.UNIPILE_DSN or not config.UNIPILE_API_KEY:
        raise ConnectError("UNIPILE_DSN and UNIPILE_API_KEY must be set to use the Unipile provider")

    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"{config.UNIPILE_DSN.rstrip('/')}/api/v1/users/invite",
            headers={"X-API-KEY": config.UNIPILE_API_KEY, "Content-Type": "application/json"},
            json={"account_id": account_id, "provider_id": profile_url, "message": note or None},
        )

    if res.status_code >= 400:
        raise ConnectError(f"Unipile {res.status_code}: {res.text[:200]}")
    return {"runUrl": None}


async def send_invite(*, profile_url: str, note: str, sender: dict, apify_token: str | None) -> dict:
    """Ek invite. `sender` me decrypted cookie/account id aata hai.

    apify_token us user ka apna hai — server ki .env wali key yahan nahi
    aati, warna ek banda dusre ke Apify credits jala deta.
    """
    provider = sender.get("provider") or config.CONNECT_PROVIDER

    if provider == "unipile":
        return await _send_via_unipile(
            profile_url=profile_url, note=note, account_id=sender.get("li_at") or ""
        )

    if not sender.get("li_at"):
        raise ConnectError("This sender account has no LinkedIn cookie saved — add it in Settings")

    return await _send_via_apify(
        profile_url=profile_url,
        note=note,
        cookies={
            "li_at": sender.get("li_at"),
            "jsessionid": sender.get("jsessionid"),
            "user_agent": sender.get("userAgent"),
        },
        token=apify_token,
    )


# ─────────────────────────── batch ───────────────────────────

async def send_batch(
    *,
    targets: list[dict],
    sender: dict,
    apify_token: str | None = None,
    on_progress: ProgressFn | None = None,
) -> list[dict]:
    """Ek-ek kar ke bhejta hai, beech me gap daal kar.

    Parallel jaan-boojh kar nahi: das invites ek second me jaana LinkedIn ke
    liye sabse saaf bot signal hai. Ek fail ho to baaki rukte nahi — har target
    ka apna result wapas jaata hai.
    """
    results: list[dict] = []
    is_premium = bool(sender.get("isPremium"))

    async def progress(**event) -> None:
        if on_progress:
            await on_progress(**event)

    for index, target in enumerate(targets):
        name = target.get("fullName") or "this person"
        note = trim_note(target.get("note"), is_premium)

        if index:
            # Thoda random jitter — ekdum barabar gap khud ek pattern hai.
            delay = config.INVITE_DELAY_SECONDS * random.uniform(0.7, 1.3)
            await progress(type="waiting", contactId=target.get("contactId"), seconds=round(delay))
            await asyncio.sleep(delay)

        await progress(type="sending", contactId=target.get("contactId"), name=name)

        try:
            out = await send_invite(
                profile_url=target["profileUrl"], note=note, sender=sender, apify_token=apify_token
            )
            result = {
                "contactId": target.get("contactId"),
                "status": "sent",
                "note": note,
                "runUrl": out.get("runUrl"),
                "error": None,
            }
        except Exception as err:
            log.warning("invite to %s failed: %s", target.get("profileUrl"), err)
            result = {
                "contactId": target.get("contactId"),
                "status": "failed",
                "note": note,
                "runUrl": None,
                "error": str(err),
            }

        results.append(result)
        await progress(type="result", **result, name=name)

    return results


# ─────────────────────────── verify ───────────────────────────

# LinkedIn non-browser user agents ko 999 deta hai, isliye ek asli UA default
# rakhna padta hai. User apna UA de de to wahi behtar — cookie aur UA ka jodha
# match karna hi sabse kam shaqi dikhta hai.
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def verify_cookie(li_at: str | None, user_agent: str | None = None) -> tuple[str, str]:
    """(status, detail) — cookie abhi zinda hai ya nahi.

    Ye sirf ek GET hai, koi invite nahi jaata.

    Redirects follow karna zaroori hai: mari hui cookie par LinkedIn pehle
    /feed/ ko 200 deta dikhta hai aur asli login page do hop baad aata hai.
    Isliye faisla final URL se hota hai, status code se nahi —
    /uas/login ya authwall matlab cookie khatam.

    Challenge/999 par hum 'unknown' bolte hain, 'ready' nahi: jhooth bol kar
    user ko poora batch bhejne dena usse kahin bura hai.
    """
    if not li_at:
        return "unverified", "No cookie saved yet"

    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            res = await client.get(
                "https://www.linkedin.com/feed/",
                headers={"User-Agent": user_agent or _DEFAULT_UA, "Accept": "text/html"},
                cookies={"li_at": li_at},
            )
    except Exception as err:
        return "unknown", f"Could not reach LinkedIn: {err}"

    final = str(res.url).lower()

    if res.status_code == 999:
        return "unknown", "LinkedIn blocked the check (999) — the cookie may still work"
    if "/checkpoint" in final or "/challenge" in final:
        return "unknown", "LinkedIn is asking this account for a security challenge — log in once in your browser"
    if "/login" in final or "authwall" in final or "signup" in final:
        return "expired", "LinkedIn sent the request to the login page — this cookie is no longer valid"
    if "/feed" in final and res.status_code == 200:
        return "ready", "LinkedIn accepted the cookie"
    return "unknown", f"Unexpected response from LinkedIn ({res.status_code} at {final[:60]})"
