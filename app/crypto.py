"""LinkedIn cookie ko DB me daalne se pehle seal karta hai.

Ye cookie password se bhi bhaari cheez hai — jiske paas `li_at` hai wo us
account ke andar hai, 2FA bhi beech me nahi aata. Isliye do niyam:

  1. DB me sirf Fernet ciphertext jaata hai, plain text kabhi nahi.
  2. Cookie kabhi browser ko wapas nahi bheji jaati. UI sirf "set hai / nahi
     hai" dekhta hai — save karne ke baad wo value dobara padhi nahi ja sakti.

Key `APP_SECRET_KEY` se aati hai. Koi bhi lambi random string chalegi: hum usse
SHA-256 kar ke 32-byte Fernet key bana lete hain, taaki user ko base64 ka
jhanjhat na ho. Key badal di to purani sealed cookies bekaar ho jaayengi —
UI unhe "re-verify chahiye" dikha dega, crash nahi hoga.
"""
import base64
import hashlib

from . import config


class SecretMissing(RuntimeError):
    """APP_SECRET_KEY set nahi hai — cookie save karne se pehle chahiye."""


def _fernet():
    # Import andar hai taaki `cryptography` install na ho to sirf ye feature
    # rukke, poori app nahi.
    from cryptography.fernet import Fernet

    secret = config.APP_SECRET_KEY
    if not secret:
        raise SecretMissing(
            "APP_SECRET_KEY is not set in .env — it is required before a LinkedIn "
            "cookie can be stored. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def ready() -> bool:
    """UI ko batane ke liye — key hai bhi ya nahi."""
    if not config.APP_SECRET_KEY:
        return False
    try:
        _fernet()
        return True
    except Exception:
        return False


def seal(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def unseal(token: str | None) -> str | None:
    """Key badal gayi ho to None — caller usse "re-verify chahiye" maanta hai."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except SecretMissing:
        raise
    except Exception:
        return None
