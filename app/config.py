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

# Sender account ki LinkedIn cookie isse encrypt hoti hai (app/crypto.py).
# Khaali ho to cookie save hi nahi hoti — plain text me rakhne se behtar hai
# feature band rahe. Koi bhi lambi random string chalegi.
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "").strip()

# Session cookie par Secure flag. Local dev http par chalta hai isliye default
# off; https deploy (Render) par 1 kar do warna cookie plain http par bhi jaayegi.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")

# Render/Railway jaise hosts apna PORT env var dete hain. Default `run.py` ke
# default se milna chahiye — warna APP_BASE_URL galat port ka link banata hai.
PORT = int(os.getenv("PORT", "10000"))

# ── forgot password / email ────────────────────────────────────────
# Reset link isi base par banta hai. Deploy par apna asli URL daalo warna
# email me localhost ka link jaayega jo user ke browser me khulega hi nahi.
APP_BASE_URL = os.getenv("APP_BASE_URL", f"http://localhost:{PORT}").strip().rstrip("/")

# SMTP. Gmail ke liye: host smtp.gmail.com, port 587, user tumhara gmail,
# pass **app password** (normal password kaam nahi karega — 2FA on karke
# myaccount.google.com/apppasswords se banao).
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "")
# From header. Khaali ho to SMTP_USER hi bhej dete hain.
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "RAYN.AI").strip()
# 587 par STARTTLS, 465 par seedha SSL. Default port se hi decide ho jaata hai.
SMTP_SSL = os.getenv("SMTP_SSL", "").strip().lower() in ("1", "true", "yes") or SMTP_PORT == 465

# ── public demo ────────────────────────────────────────────────────
# LinkedIn par share karne ke liye ek read-only account. Visitor bina signup
# ke andar aa jaata hai aur ek purana run poora ghoom kar dekh sakta hai —
# jobs, scores, contacts, drafts. Paisa kharch karne wala koi bhi button us
# account par band rehta hai, warna ek post ke baad Apify balance saaf.
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@rayn.ai").strip().lower()
DEMO_ENABLED = os.getenv("DEMO_ENABLED", "1").strip().lower() not in ("0", "false", "no")

# Reset link kitni der chalega. Chhota rakha hai — mail me pada link jitni
# der zinda rahega, utni der khatra rahega.
RESET_TOKEN_MINUTES = int(os.getenv("RESET_TOKEN_MINUTES", "30"))

MIN_LIMIT = 10
MAX_LIMIT = 30

# Reach-out ka rule: itne se kam employees wali company me seedha founder/CTO
# ko likho, usse badi me HR/recruiter ko. Company size na pata chale to HR —
# bade organisation ke CEO ko DM karna ulta padta hai.
FOUNDER_MAX_EMPLOYEES = int(os.getenv("FOUNDER_MAX_EMPLOYEES", "50"))

# ── decision makers + connection requests ──────────────────────────
# Discovery cookie ke bina chalti hai (public profiles), isliye default actor
# wahi hai. Sending ke liye cookie lazmi hai — koi official API nahi hai.
PEOPLE_ACTOR = os.getenv("PEOPLE_ACTOR", "apt_marble/linkedin-decision-makers-scraper-ceos-founders-executives").strip()
CONNECT_ACTOR = os.getenv("CONNECT_ACTOR", "data_link_miner/linkedin-network-connection-request").strip()

# 'apify' ya 'unipile'. Unipile paid hai par asal me chalta hai; Apify ke
# connect actors saste hain aur bharose ke laayak kam. app/connect.py dono
# ko ek hi interface ke peeche rakhta hai.
CONNECT_PROVIDER = os.getenv("CONNECT_PROVIDER", "apify").strip() or "apify"
UNIPILE_DSN = os.getenv("UNIPILE_DSN", "").strip()
UNIPILE_API_KEY = os.getenv("UNIPILE_API_KEY", "").strip()

# Ek "Send" click me itne se zyada invite nahi. UI 5-7 par bana hai; ye uski
# hard ceiling hai taaki koi galti se 50 select kar ke na bhej de.
MAX_BATCH_INVITES = int(os.getenv("MAX_BATCH_INVITES", "10"))
# LinkedIn ki apni limit weekly ~100-200 hai. Hum uske aas-paas bhi nahi
# jaate — restriction ek baar lag gayi to account wapas nahi milta.
DAILY_INVITE_CAP = int(os.getenv("DAILY_INVITE_CAP", "20"))
WEEKLY_INVITE_CAP = int(os.getenv("WEEKLY_INVITE_CAP", "100"))
# Do invites ke beech ka gap (seconds) — burst sabse aasaan detection signal hai.
INVITE_DELAY_SECONDS = float(os.getenv("INVITE_DELAY_SECONDS", "25"))

# Free account par personalised note ~5/month par khatam ho jaata hai aur 200
# char me katta hai; Premium par 300. Isliye note yahin trim hota hai.
NOTE_LIMIT_FREE = 200
NOTE_LIMIT_PREMIUM = 300

# Apify credits ka mota-mota estimate — frontend pehle khud jodta tha,
# ab ek hi jagah rehta hai taaki DB me likha hua kharcha bhi wahi ho.
COST_PER_JOB = 0.0026

# JD upload ki limit — 10 MB se bada PDF matlab kuch galat hai.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm", ".rtf", ".pptx"}
