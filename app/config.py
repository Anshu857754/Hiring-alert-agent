"""Ek jagah se saari settings — .env project root se load hoti hai."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"

load_dotenv(ROOT / ".env")

APIFY_API_KEY = os.getenv("APIFY_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "3000"))

MIN_LIMIT = 10
MAX_LIMIT = 30

# JD upload ki limit — 10 MB se bada PDF matlab kuch galat hai.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm", ".rtf", ".pptx"}
