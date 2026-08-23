"""API keys aur LinkedIn cookie ko DB me daalne se pehle seal karta hai.

Cookie to password se bhi bhaari cheez hai — jiske paas `li_at` hai wo us
account ke andar hai, 2FA bhi beech me nahi aata. Isliye do niyam:

  1. DB me sirf Fernet ciphertext jaata hai, plain text kabhi nahi.
  2. Value kabhi browser ko wapas nahi jaati. UI sirf "set hai / nahi hai"
     dekhta hai — save karne ke baad wo dobara padhi nahi ja sakti.

**Key kahan se aati hai**

Pehli pasand `APP_SECRET_KEY` hai. Wo set na ho to `DATABASE_URL` se ek key
derive kar li jaati hai. Ye jhol nahi hai, soch kar rakha hai:

* Jo cheez hum bacha rahe hain wo DB dump hai. Attacker ke paas dump hai par
  `DATABASE_URL` nahi (wo env me rehti hai, DB me nahi) — to derive bhi nahi
  kar sakta. Yaani "at rest" wali suraksha waisi ki waisi rehti hai.
* Jiske paas env ka access hai usko `APP_SECRET_KEY` waise bhi mil jaati.
  Dono soorat me security ek jaisi hai.
* Sabse bada fayda: ek hi database use karne wale saare environments (local,
  Render) apne aap ek hi key par aa jaate hain. Pehle ek jagah variable set
  karna bhool jaao to dusri jagah ki sealed keys khulti hi nahi thi, aur
  "Save" button bina kisi raaste ke disabled pada rehta tha.

Decrypt karte waqt **dono** keys try hoti hain (MultiFernet). Isliye purani
`APP_SECRET_KEY` se sealed cheezein baad me bhi khulti rehti hain.

Dhyan: `DATABASE_URL` badal do (jaise Neon ka password rotate) to derived key
bhi badal jaati hai aur usse sealed values bekaar ho jaati hain — bilkul waise
hi jaise `APP_SECRET_KEY` badalne par hota hai. UI unhe "dobara daalo" dikha
deta hai, crash kahin nahi hota.
"""
import base64
import hashlib
import logging

from . import config

log = logging.getLogger("hiring-agent.crypto")


class SecretMissing(RuntimeError):
    """Na APP_SECRET_KEY hai na DATABASE_URL — kuch bhi seal nahi ho sakta."""


# Derived key ka pehla istemaal ek baar log karo, har request par nahi.
_warned = False


def _key_from(secret: str) -> bytes:
    """Koi bhi string → 32-byte Fernet key. User ko base64 ka jhanjhat nahi."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _secrets() -> list[str]:
    """Pehla element se encrypt hota hai; saare decrypt ke liye try hote hain."""
    out: list[str] = []
    if config.APP_SECRET_KEY:
        out.append(config.APP_SECRET_KEY)
    if config.DATABASE_URL:
        # Namespace laga dete hain taaki ye value kahin aur ki hashing se na
        # takraye — derive sirf isi kaam ke liye ho.
        out.append("hiring-agent:key-encryption:v1:" + config.DATABASE_URL)
    return out


def _fernet():
    # Import andar hai taaki `cryptography` install na ho to sirf ye feature
    # rukke, poori app nahi.
    from cryptography.fernet import Fernet, MultiFernet

    secrets = _secrets()
    if not secrets:
        raise SecretMissing(
            "Neither APP_SECRET_KEY nor DATABASE_URL is set, so API keys and cookies "
            "cannot be encrypted. Set APP_SECRET_KEY — generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )

    global _warned
    if not config.APP_SECRET_KEY and not _warned:
        log.warning(
            "APP_SECRET_KEY not set — using a key derived from DATABASE_URL. This works, "
            "but set APP_SECRET_KEY explicitly so the two can be rotated independently."
        )
        _warned = True

    return MultiFernet([Fernet(_key_from(s)) for s in secrets])


def ready() -> bool:
    """UI ko batane ke liye — encrypt karne layak kuch hai bhi ya nahi."""
    if not _secrets():
        return False
    try:
        _fernet()
        return True
    except Exception:
        return False


def derived_only() -> bool:
    """True = chal to raha hai, par APP_SECRET_KEY set karna behtar hoga."""
    return bool(config.DATABASE_URL) and not config.APP_SECRET_KEY


def seal(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def unseal(token: str | None) -> str | None:
    """Koi bhi key match kare to khul jaata hai; warna None — caller usse
    "dobara daalna padega" maanta hai."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except SecretMissing:
        raise
    except Exception:
        return None
