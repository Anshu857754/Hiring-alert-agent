"""Email bhejna — abhi sirf password reset ke liye.

`smtplib` stdlib me hai, isliye koi nayi dependency nahi lagi. Bhejna blocking
hai to `asyncio.to_thread` me chalta hai — wahi tarika jo `app/db.py` use karta
hai (Windows par uvicorn ka ProactorEventLoop async SMTP ke saath jhagadta hai).

SMTP configure na ho to app crash nahi hoti: `configured()` False deta hai aur
caller reset link server ke log me likh deta hai. Link browser ko kabhi nahi
jaata — warna koi bhi ajnabi kisi ka bhi email daal ke uska account khol leta.
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from datetime import datetime, timezone

import httpx

from . import config

log = logging.getLogger("hiring-agent.mailer")


def provider() -> str | None:
    """Kaunse raaste se mail jaayegi. Pehla jo set ho wahi jeetta hai.

    HTTP wale pehle hain kyunki Render ke free plan par SMTP ports block hote
    hain — wahan Gmail SMTP chup-chaap timeout ho jaata hai.
    """
    if not config.SMTP_FROM:
        return None
    if config.BREVO_API_KEY:
        return "brevo"
    if config.RESEND_API_KEY:
        return "resend"
    if config.SMTP_HOST:
        return "smtp"
    return None


def configured() -> bool:
    return provider() is not None


def status() -> dict:
    """UI ko sirf itna pata chalta hai ki email nikal sakti hai ya nahi."""
    return {"configured": configured(), "provider": provider()}


def _send_sync(msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    if config.SMTP_SSL:
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20, context=context)
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
    with server:
        server.ehlo()
        if not config.SMTP_SSL:
            server.starttls(context=context)
            server.ehlo()
        # Kuch relay (local postfix, MailHog) bina auth ke chalte hain.
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASS)
        server.send_message(msg)


# ─────────────────────────── HTTP providers ───────────────────────────
# Ye 443 par jaate hain, isliye SMTP block hone se farak nahi padta.


async def _send_brevo(to: str, subject: str, text: str, html: str | None) -> None:
    payload = {
        "sender": {"email": config.SMTP_FROM, "name": config.SMTP_FROM_NAME},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        payload["htmlContent"] = html

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": config.BREVO_API_KEY, "accept": "application/json"},
            json=payload,
        )
    if res.status_code >= 300:
        raise RuntimeError(f"Brevo rejected the email ({res.status_code}): {res.text[:300]}")


async def _send_resend(to: str, subject: str, text: str, html: str | None) -> None:
    payload = {
        "from": f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM}>",
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            json=payload,
        )
    if res.status_code >= 300:
        raise RuntimeError(f"Resend rejected the email ({res.status_code}): {res.text[:300]}")


async def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Bhej do. Fail hone par exception uthta hai — caller decide kare kya karna hai."""
    how = provider()
    if not how:
        raise RuntimeError(
            "No email provider configured — set SMTP_FROM plus one of "
            "BREVO_API_KEY / RESEND_API_KEY / SMTP_HOST"
        )

    if how == "brevo":
        await _send_brevo(to, subject, text, html)
    elif how == "resend":
        await _send_resend(to, subject, text, html)
    else:
        msg = EmailMessage()
        msg["From"] = formataddr((config.SMTP_FROM_NAME, config.SMTP_FROM))
        msg["To"] = to
        msg["Subject"] = subject
        # Ye teen headers spam filters dekhte hain. Message-ID aur Date ke
        # bina mail "kisi script ne bheja hai" jaisi lagti hai; Reply-To se
        # banda jawab de sake. Auto-Submitted batata hai ki ye transactional
        # hai, isliye koi auto-responder isse loop me nahi daalta.
        msg["Message-ID"] = make_msgid(domain=config.SMTP_FROM.split("@")[-1])
        msg["Date"] = format_datetime(datetime.now(timezone.utc))
        msg["Reply-To"] = config.SMTP_FROM
        msg["Auto-Submitted"] = "auto-generated"
        # Plain text pehle, HTML uske baad — yahi sahi multipart/alternative
        # order hai. Sirf HTML bhejna spam score badha deta hai.
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")

        await asyncio.to_thread(_send_sync, msg)

    log.info("email sent to %s via %s (%s)", to, how, subject)


# ─────────────────────────── password reset ───────────────────────────

def _reset_bodies(name: str, link: str, minutes: int) -> tuple[str, str]:
    text = (
        f"Hi {name},\n\n"
        f"Someone asked to reset the password for your RAYN.AI account.\n"
        f"Open this link to choose a new one:\n\n"
        f"{link}\n\n"
        f"The link works once and expires in {minutes} minutes.\n"
        f"If this wasn't you, ignore this email — your password stays as it is.\n"
    )
    html = f"""\
<div style="font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;
            max-width:480px;margin:0 auto;padding:24px;color:#1f2330;line-height:1.6">
  <p style="font-size:18px;font-weight:600;margin:0 0 4px">Reset your password</p>
  <p style="margin:0 0 20px;color:#5b6070">Hi {name}, someone asked to reset the password
     for your RAYN.AI account.</p>
  <p style="margin:0 0 24px">
    <a href="{link}"
       style="display:inline-block;background:#5b53e8;color:#fff;text-decoration:none;
              padding:11px 22px;border-radius:8px;font-weight:600">Choose a new password</a>
  </p>
  <p style="margin:0 0 8px;color:#5b6070;font-size:13px">
     The link works once and expires in {minutes} minutes.</p>
  <p style="margin:0;color:#5b6070;font-size:13px">
     If this wasn't you, ignore this email — your password stays as it is.</p>
</div>"""
    return text, html


async def send_password_reset(to: str, name: str, link: str) -> bool:
    """True = email nikal gayi. False = SMTP set nahi hai ya bhejne me dikkat aayi.

    Dono soorat me link log me jaata hai taaki admin haath se bhej sake, aur
    caller user ko hamesha ek jaisa jawab de sake.
    """
    minutes = config.RESET_TOKEN_MINUTES
    text, html = _reset_bodies(name or "there", link, minutes)

    if not configured():
        log.warning("no email provider configured — password reset link for %s: %s", to, link)
        return False

    try:
        await send(to, "Reset your RAYN.AI password", text, html)
        return True
    except Exception:
        log.exception("could not email the reset link to %s — link: %s", to, link)
        return False
