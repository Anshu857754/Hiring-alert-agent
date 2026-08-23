"""Accounts, passwords aur sessions.

Koi auth library nahi lagayi — zaroorat hi nahi thi:

* **Password**: `hashlib.scrypt` stdlib me hai aur memory-hard hai (bcrypt/argon2
  wali hi family). Har user ka apna salt, aur compare `compare_digest` se hota
  hai taaki galat password ka jawab hamesha ek jitna time le.
* **Session**: server-side token (`sessions` table). Signed cookie bhi chal
  jaati par usme logout sirf browser se cookie hataata — token phir bhi zinda
  rehta. Yahan logout row delete karta hai, matlab sach me revoke.

Har user apni Apify/OpenRouter keys deta hai. Wo bhi Fernet se sealed rehti
hain aur browser ko kabhi wapas nahi jaati — sirf "set hai / nahi hai".
"""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from psycopg.errors import UniqueViolation

from . import config, crypto, db
from .db import S

log = logging.getLogger("hiring-agent.users")

SESSION_COOKIE = "ha_session"
SESSION_DAYS = 30

# scrypt parameters. n=2**14 laptop par ~50-80ms leta hai — login ke liye
# theek, aur brute force ke liye mehnga.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD = 8


class AuthError(Exception):
    """Message seedha user ko dikhta hai — isliye hamesha padhne layak rakho.

    `code` optional hai. Frontend ko kuch case me sirf text se zyada chahiye
    hota hai (jaise "email pehle se hai" par "Sign in instead" wala button
    dikhana) — tab message ka string match karne se behtar hai ek code bhejna.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


# ─────────────────────────── password ───────────────────────────

def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=64
    ).hex()


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    return _hash(password, salt), salt.hex()


def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(_hash(password, salt), stored_hash)


def validate_signup(email: str, password: str) -> tuple[str, str]:
    """Saaf-suthri validation — errors wahi jo user ko samajh aayein."""
    email = (email or "").strip().lower()
    password = password or ""

    if not _EMAIL_RE.match(email):
        raise AuthError("That does not look like an email address")
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters")
    return email, password


# ─────────────────────────── users ───────────────────────────

def _user_out(row: dict) -> dict:
    """Browser ke liye. Password aur keys yahan se kabhi nahi nikalte."""
    created = row.get("created_at")
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "name": row.get("name") or (row.get("email") or "").split("@")[0],
        "createdAt": created.isoformat() if created else None,
        "hasApifyKey": bool(row.get("apify_key_enc")),
        "hasOpenRouterKey": bool(row.get("openrouter_key_enc")),
    }


async def count_users() -> int:
    row = await db.fetch_one(f"SELECT count(*) AS n FROM {S}users")
    return int(row["n"]) if row else 0


async def create_user(email: str, password: str, name: str | None = None) -> dict:
    email, password = validate_signup(email, password)

    existing = await db.fetch_one(f"SELECT id FROM {S}users WHERE lower(email) = %s", (email,))
    if existing:
        raise AuthError(f"{email} is already registered", code="email_taken")

    password_hash, salt = hash_password(password)

    # Pehla banda hi orphan rows ka maalik banta hai (neeche adopt_orphans).
    first_user = await count_users() == 0

    try:
        row = await db.fetch_one(
            f"""
            INSERT INTO {S}users (email, name, password_hash, password_salt)
            VALUES (%s, %s, %s, %s)
         RETURNING *
            """,
            (email, (name or "").strip() or None, password_hash, salt),
        )
    except UniqueViolation:
        # Do signups ek hi email par ek saath aa gaye. Upar wala SELECT dono me
        # khaali laut sakta hai — asli faisla users_email_uniq index karta hai.
        raise AuthError(f"{email} is already registered", code="email_taken") from None
    if not row:
        raise AuthError("Could not create the account — the database rejected it")

    if first_user:
        adopted = await adopt_orphans(row["id"])
        if adopted:
            log.info("first user %s adopted %s pre-existing row(s)", email, adopted)

    return _user_out(row)


async def authenticate(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    row = await db.fetch_one(f"SELECT * FROM {S}users WHERE lower(email) = %s", (email,))

    # User na mile tab bhi hash chalate hain — warna response time se pata chal
    # jaata hai ki ye email registered hai ya nahi.
    if not row:
        _hash(password or "", b"timing-equaliser")
        raise AuthError("Wrong email or password")

    if not verify_password(password or "", row["password_hash"], row["password_salt"]):
        raise AuthError("Wrong email or password")

    await db.execute(f"UPDATE {S}users SET last_login_at = now() WHERE id = %s", (row["id"],))
    return _user_out(row)


async def get_user(user_id: int) -> dict | None:
    row = await db.fetch_one(f"SELECT * FROM {S}users WHERE id = %s", (user_id,))
    return _user_out(row) if row else None


async def change_password(user_id: int, current: str, new: str) -> None:
    row = await db.fetch_one(f"SELECT * FROM {S}users WHERE id = %s", (user_id,))
    if not row:
        raise AuthError("Account not found")
    if not verify_password(current or "", row["password_hash"], row["password_salt"]):
        raise AuthError("Your current password is wrong")
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"New password must be at least {MIN_PASSWORD} characters")

    password_hash, salt = hash_password(new)
    await db.execute(
        f"UPDATE {S}users SET password_hash = %s, password_salt = %s WHERE id = %s",
        (password_hash, salt, user_id),
    )
    # Password badla to baaki devices ke sessions gir jaane chahiye.
    await db.execute(f"DELETE FROM {S}sessions WHERE user_id = %s", (user_id,))


# ─────────────────────────── password reset ───────────────────────────
# Email me raw token jaata hai, DB me sirf uska sha256. DB leak ho jaaye to
# bhi koi link nahi bana sakta. Yahan scrypt ki zaroorat nahi — token khud
# 32 random bytes ka hai, guess karne layak kuch hai hi nahi.


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


async def create_reset_token(email: str, ip: str | None = None) -> tuple[dict, str] | None:
    """Naya reset token. Email registered na ho to None — caller phir bhi wahi
    generic jawab deta hai, taaki koi is route se emails na sungh sake."""
    email = (email or "").strip().lower()
    row = await db.fetch_one(f"SELECT * FROM {S}users WHERE lower(email) = %s", (email,))
    if not row:
        return None

    # Purane token bekaar — warna mail me pade 4 links ek saath zinda rehte.
    await db.execute(f"DELETE FROM {S}password_resets WHERE user_id = %s", (row["id"],))

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=config.RESET_TOKEN_MINUTES)
    await db.execute(
        f"""
        INSERT INTO {S}password_resets (token_hash, user_id, expires_at, requested_ip)
        VALUES (%s, %s, %s, %s)
        """,
        (_token_hash(token), row["id"], expires, (ip or "")[:60] or None),
    )
    log.info("password reset requested for %s", email)
    return _user_out(row), token


async def _live_reset(token: str) -> dict | None:
    """Token ka row + user, tabhi jab wo abhi tak valid ho."""
    if not token:
        return None
    return await db.fetch_one(
        f"""
        SELECT r.token_hash, r.user_id, u.email, u.name
          FROM {S}password_resets r
          JOIN {S}users u ON u.id = r.user_id
         WHERE r.token_hash = %s AND r.used_at IS NULL AND r.expires_at > now()
        """,
        (_token_hash(token),),
    )


async def check_reset_token(token: str) -> dict:
    """Form dikhane se pehle frontend yahi poochta hai — taaki user 8 character
    ka password type karne ke baad "link expired" na dekhe."""
    row = await _live_reset(token)
    if not row:
        raise AuthError("This reset link is invalid or has expired — request a new one")
    return {"email": row["email"], "name": row["name"]}


async def reset_password(token: str, new: str) -> dict:
    """Token se password badlo. Token ek hi baar chalta hai."""
    row = await _live_reset(token)
    if not row:
        raise AuthError("This reset link is invalid or has expired — request a new one")
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"New password must be at least {MIN_PASSWORD} characters")

    password_hash, salt = hash_password(new)
    await db.execute(
        f"UPDATE {S}users SET password_hash = %s, password_salt = %s WHERE id = %s",
        (password_hash, salt, row["user_id"]),
    )
    # Token jala do, aur us user ke saare purane sessions bhi — reset ki wajah
    # aksar "account kisi aur ke paas chala gaya" hoti hai.
    await db.execute(
        f"UPDATE {S}password_resets SET used_at = now() WHERE token_hash = %s", (row["token_hash"],)
    )
    await db.execute(f"DELETE FROM {S}sessions WHERE user_id = %s", (row["user_id"],))
    log.info("password reset completed for %s", row["email"])
    return {"email": row["email"]}


async def purge_expired_resets() -> int:
    return await db.execute(
        f"DELETE FROM {S}password_resets WHERE expires_at <= now() OR used_at IS NOT NULL"
    )


# ─────────────────────────── API keys ───────────────────────────

async def save_keys(user_id: int, *, apify: str | None, openrouter: str | None) -> dict | None:
    """Khaali string bhejo to key hat jaati hai; None bhejo to jaisi thi waisi rehti hai."""
    apify_enc = crypto.seal(apify) if apify else None
    openrouter_enc = crypto.seal(openrouter) if openrouter else None

    row = await db.fetch_one(
        f"""
        UPDATE {S}users
           SET apify_key_enc      = CASE WHEN %s THEN %s ELSE apify_key_enc END,
               openrouter_key_enc = CASE WHEN %s THEN %s ELSE openrouter_key_enc END
         WHERE id = %s
     RETURNING *
        """,
        (apify is not None, apify_enc, openrouter is not None, openrouter_enc, user_id),
    )
    return _user_out(row) if row else None


async def get_keys(user_id: int) -> dict:
    """Decrypted keys — sirf server-side use ke liye, response me kabhi nahi.

    Key badal gayi ho (APP_SECRET_KEY) to unseal None deta hai; caller usse
    "key set nahi hai" maanta hai aur user ko dobara paste karne ko kehta hai.
    """
    row = await db.fetch_one(
        f"SELECT apify_key_enc, openrouter_key_enc FROM {S}users WHERE id = %s", (user_id,)
    )
    if not row:
        return {"apify": None, "openrouter": None}
    return {
        "apify": crypto.unseal(row.get("apify_key_enc")),
        "openrouter": crypto.unseal(row.get("openrouter_key_enc")),
    }


# ─────────────────────────── sessions ───────────────────────────

async def start_session(user_id: int, user_agent: str | None = None) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    await db.execute(
        f"INSERT INTO {S}sessions (token, user_id, expires_at, user_agent) VALUES (%s, %s, %s, %s)",
        (token, user_id, expires, (user_agent or "")[:300] or None),
    )
    return token, expires


async def user_for_session(token: str | None) -> dict | None:
    if not token:
        return None
    row = await db.fetch_one(
        f"""
        SELECT u.*
          FROM {S}sessions s
          JOIN {S}users u ON u.id = s.user_id
         WHERE s.token = %s AND s.expires_at > now()
        """,
        (token,),
    )
    return _user_out(row) if row else None


async def end_session(token: str | None) -> None:
    if token:
        await db.execute(f"DELETE FROM {S}sessions WHERE token = %s", (token,))


async def purge_expired_sessions() -> int:
    return await db.execute(f"DELETE FROM {S}sessions WHERE expires_at <= now()")


# ─────────────────────────── migration helper ───────────────────────────

# Multi-user se pehle ka data kisi ka nahi tha (user_id NULL). Pehla signup
# use apna bana leta hai — warna Anshu ki poori history gayab dikhti.
_ORPHAN_TABLES = ("searches", "saved_jobs", "plans", "outreach", "contacts", "sender_accounts")


async def adopt_orphans(user_id: int) -> int:
    total = 0
    for table in _ORPHAN_TABLES:
        total += await db.execute(
            f"UPDATE {S}{table} SET user_id = %s WHERE user_id IS NULL", (user_id,)
        )
    return total
