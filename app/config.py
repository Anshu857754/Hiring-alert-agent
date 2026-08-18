"""Ek jagah se saari settings — .env project root se load hoti hai."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"
MIGRATIONS_DIR = ROOT / "migrations"

load_dotenv(ROOT / ".env")

APIFY_API_KEY = os.getenv("APIFY_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

# Neon Postgres. Khaali ho to app chalti rahegi, bas kuch save nahi hoga.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# Ye database dusre project ke saath share hota hai, isliye apni tables
# alag schema me rakhte hain — naam kabhi takraayenge nahi.
DB_SCHEMA = os.getenv("DB_SCHEMA", "hiring_agent").strip() or "hiring_agent"
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "8"))

# Password gate. APP_PASSWORD khaali ho to app bilkul khuli rehti hai —
# local dev me yahi theek hai, par public deploy par set karna zaroori hai.
APP_USERNAME = os.getenv("APP_USERNAME", "admin").strip() or "admin"
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()

# Render/Railway jaise hosts apna PORT env var dete hain.
PORT = int(os.getenv("PORT", "3000"))

MIN_LIMIT = 10
MAX_LIMIT = 30

# Apify credits ka mota-mota estimate — frontend pehle khud jodta tha,
# ab ek hi jagah rehta hai taaki DB me likha hua kharcha bhi wahi ho.
COST_PER_JOB = 0.0026

# JD upload ki limit — 10 MB se bada PDF matlab kuch galat hai.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm", ".rtf", ".pptx"}
