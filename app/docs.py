"""PDF / DOCX ko markdown text me badalta hai — poori tarah local, koi LLM call nahi.

MarkItDown andar hi pdfminer/mammoth use karta hai, isliye JD upload karne ka
koi token cost nahi lagta. LLM sirf tab chalta hai jab search actually hoti hai.
"""
import asyncio
import re
import tempfile
from pathlib import Path

from markitdown import MarkItDown

from .config import ALLOWED_UPLOAD_EXTS

# MarkItDown instance thread-safe reuse ke liye ek hi baar banate hain.
_md = MarkItDown(enable_plugins=False)


def _tidy(text: str) -> str:
    """PDF se aane wale extra blank lines aur trailing spaces saaf karte hain."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # PDF me kabhi kabhi har page par same header/footer aata hai — usse hata dete hain.
    return text.strip()


def _convert_sync(data: bytes, suffix: str) -> str:
    # MarkItDown ko file path dena sabse reliable hai (extension se converter chunta hai).
    tmp = Path(tempfile.mkdtemp(prefix="hiring-agent-")) / f"upload{suffix}"
    try:
        tmp.write_bytes(data)
        result = _md.convert(str(tmp))
        return _tidy(getattr(result, "text_content", "") or "")
    finally:
        tmp.unlink(missing_ok=True)
        tmp.parent.rmdir()


class UnsupportedFile(ValueError):
    pass


async def extract_text(filename: str, data: bytes) -> dict:
    """File ka text nikaal kar {text, chars, words} return karta hai."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTS:
        raise UnsupportedFile(
            f"'{suffix or filename}' is not supported. Please use PDF, DOCX, TXT, MD, HTML or PPTX."
        )

    # markitdown blocking hai, isliye thread me chalate hain warna event loop atak jaata hai.
    text = await asyncio.to_thread(_convert_sync, data, suffix)

    return {"text": text, "chars": len(text), "words": len(text.split())}
