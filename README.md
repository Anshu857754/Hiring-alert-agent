# Hiring Agent

Job description daalo (ya PDF upload karo) → AI usse search query banata hai → LinkedIn + Indeed scrape hote hain → har job ko JD ke against 0-100 match score milta hai → sorted table.

Backend **FastAPI (Python)**, frontend plain **HTML + CSS + JS** (koi build step nahi).

---

## Flow

```
Job Description  ──  paste karo  ya  PDF/DOCX upload karo
                                        ↓
                              markitdown (local, $0)  ──→ text
      ↓
DeepSeek v4 Pro  ──→  search params nikaale (title, location, country, skills)
      ↓
Apify (parallel)  ──→  LinkedIn scraper + Indeed scraper
      ↓
normalize + dedupe (URL ke basis par)
      ↓
DeepSeek v4 Pro  ──→  har job ko JD ke against score (batches of 15)
      ↓
Table — best match sabse upar
```

---

## Setup

`.env` file me do keys chahiye:

```
APIFY_API_KEY=apify_api_xxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx
```

Install aur run (Python 3.10+):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python run.py
```

Phir browser me kholo: **http://localhost:3000**

Dev me auto-reload chahiye to:

```bash
uvicorn app.main:app --reload --port 3000
```

---

## Files

| File | Kaam |
|---|---|
| `run.py` | Entry point — uvicorn ko port 3000 par start karta hai |
| `app/main.py` | FastAPI app. `POST /api/search` NDJSON stream, `POST /api/extract` file→text, `GET /api/health` |
| `app/llm.py` | OpenRouter calls — `deepseek/deepseek-v4-pro`. Do kaam: JD parse karna + jobs ko score karna |
| `app/apify.py` | Dono scrapers chalata hai, output normalize karta hai, duplicates hatata hai |
| `app/docs.py` | markitdown wrapper — PDF/DOCX se text nikaalta hai (local, koi LLM call nahi) |
| `app/config.py` | `.env` load, limits, allowed file types |
| `public/index.html` | UI markup |
| `public/styles.css` | Poora dark theme |
| `public/app.js` | Tabs, file upload, NDJSON stream padhna, table sort/filter/CSV |
| `scrape-jobs.js` | Purana Node CLI — sirf scraping ke liye, abhi bhi chalta hai |

**Note:** `server.js` purana Express backend hai. Ab use karne ki zaroorat nahi — naya UI `/api/extract` aur `/api/health` use karta hai jo usme nahi hain, isliye `npm start` par PDF upload kaam nahi karega. `python run.py` hi chalao.

---

## API

| Endpoint | Kya karta hai |
|---|---|
| `GET /api/health` | model name + `.env` me keys hain ya nahi |
| `POST /api/extract` | multipart `file` → `{ text, chars, words, filename }` |
| `POST /api/search` | `{ jobDescription, limit, source, useAi }` → NDJSON stream |

`/api/search` ke stream events:

```
{"type":"progress","stage":"parse|scrape|linkedin|indeed|score","message":"...","isError":false}
{"type":"params","params":{...},"limit":50}
{"type":"done","jobs":[...],"params":{...},"usage":{...},"model":"..."}
{"type":"error","message":"..."}
```

---

## PDF / DOCX upload (markitdown)

UI me **"PDF / DOCX upload"** tab hai — file drop karo ya click karke chuno.

- Backend `markitdown` se text nikaalta hai — **poora local**, koi API call nahi, koi token cost nahi. Iseeliye Gemini/GPT se PDF padhwane wala jugaad nahi kiya.
- Support: `.pdf` `.docx` `.doc` `.pptx` `.txt` `.md` `.html` `.htm` `.rtf` — max **10 MB**
- Nikla hua text seedha JD box me chala jaata hai, upload ke neeche preview bhi dikhta hai. "Text edit karo" pe click karke paste tab me jaake usme changes kar sakte ho — search wahi final text use karti hai.
- **Scanned PDF (sirf images) me text nahi milega** — markitdown OCR nahi karta, aisi file par saaf error dikhega.

markitdown blocking library hai, isliye `asyncio.to_thread` me chalati hai taaki bada PDF server ko block na kare.

---

## UI

- **Job Description** — paste karo ya PDF daalo (minimum 20 characters)
- **Limit slider** — 50 se 200 tak, step 10. Ye *per source* hai, to "both" pe 200 matlab ~400 jobs
- **Sources** — LinkedIn + Indeed / sirf LinkedIn / sirf Indeed
- **AI Matching toggle** — off karoge to scraping to hogi par score nahi milega (aur OpenRouter cost bhi nahi lagega)
- **Live log** — scraping me 30-60 second lagte hain, isliye har step ka update dikhta hai
- **Table** — match score + reason, source badge, clickable job title, company, location, type, level, salary, posted date
- Column header pe click karke sort, filter box, aur CSV download

---

## CLI (UI ke bina)

```bash
node scrape-jobs.js --title "Backend Engineer" --location "Pune" --country IN --limit 50
```

| Flag | Default | Note |
|---|---|---|
| `--title` | `Software Engineer` | search keyword |
| `--location` | `Bengaluru` | city ya region |
| `--country` | `IN` | 2-letter code, sirf Indeed ke liye |
| `--limit` | `25` | per source |
| `--source` | `both` | `both` / `linkedin` / `indeed` |

Output `jobs-<timestamp>.json` aur `.csv` me save hota hai. CLI me AI wala hissa nahi hai — wo sirf scraping karta hai.

---

## Apify Actors

| Source | Actor | Note |
|---|---|---|
| LinkedIn | `curious_coder/linkedin-jobs-scraper` | pay-per-event, FREE plan pe chalta hai |
| Indeed | `misceres/indeed-scraper` | pay-per-event |

**`bebity/linkedin-jobs-scraper` kyun nahi:** us actor ka free trial khatam ho chuka hai, ab paid monthly rental maangta hai. Isliye pay-per-event wale par switch kiya.

---

## Cost

Account FREE plan par hai — **$5/month** ki limit.

Roughly **$0.0026 per job** lagta hai:

| Limit | Sources | Jobs | Approx cost |
|---|---|---|---|
| 50 | both | 100 | ~$0.26 |
| 100 | both | 200 | ~$0.52 |
| 200 | both | 400 | ~$1.04 |

UI me slider ke neeche estimated cost live dikhta hai.

OpenRouter alag se charge karta hai par bahut kam — 100 jobs score karne me ~34k tokens (~$0.06). Descriptions 700 characters tak trim karke 15-15 ke batches me bhejte hain isliye sasta padta hai.

**PDF parsing ka cost zero hai** — markitdown local chalti hai.

Usage check karne ke liye:

```bash
curl -s "https://api.apify.com/v2/users/me/limits?token=$APIFY_API_KEY"
```

---

## Job object

```python
{
  "source": "linkedin" | "indeed",
  "title": ..., "company": ..., "location": ...,
  "postedAt": ...,        # LinkedIn: "2026-08-03" | Indeed: "Just posted" (format alag hai)
  "contractType": ...,    # Full-time, Contract...
  "experienceLevel": ..., # sirf LinkedIn
  "workType": ...,        # Remote / Hybrid
  "salary": ...,          # zyadatar null — dono portals par kam hi milta hai
  "url": ..., "applyUrl": ...,
  "applicants": ...,      # sirf LinkedIn
  "description": ...,
  "matchScore": ...,      # 0-100, sirf AI on hone par
  "matchReason": ...      # ek chhoti line
}
```

---

## Dhyan rakhne layak baatein

- **Salary zyadatar khaali aata hai** — LinkedIn/Indeed par postings me salary aksar hoti hi nahi. Test run me 60 me se sirf 2 me mili.
- **`postedAt` ka format alag hai** — LinkedIn actual date deta hai, Indeed relative text ("Just posted", "3 days ago"). Abhi normalize nahi kiya.
- **LinkedIn me same company ki repeat postings** aati hain (jaise Accenture ke 13 listings). Ye actual alag-alag job IDs hain, duplicate nahi — dedupe URL par hota hai.
- **Apify data 7 din me delete ho jaata hai** (free plan retention), isliye jo chahiye wo CSV download kar lena.
- **Browser tab band karoge to background pipeline cancel ho jaata hai** — stream toot-te hi task cancel hota hai, credits bachte hain.
- `.env` `.gitignore` me hai — commit mat karna.

---

## Test run

**FastAPI + PDF upload wala run (14 Aug 2026)** — asli browser me, JD ek PDF se aayi:

- PDF → markitdown → 312 chars / 48 words, koi LLM call nahi
- LLM ne JD se search banayi: `"Senior Backend Engineer" in Bengaluru (IN)`, seniority `senior`, skills Python/FastAPI/PostgreSQL/AWS/Kafka/Redis
- Indeed se 50 jobs, saare 50 score huye (4 batches), total ~2 minute
- Top match: **Drongo AI — Senior Backend Developer, 89/100** — *"Strong Python/FastAPI backend match; PostgreSQL/AWS unspecified"*
- Neeche wale rows 20-45 par gaye (PERL/.NET/Golang/Java roles), matlab scoring sahi discriminate kar rahi hai
- AI tokens: 20,107

Purana Node backend wala run (limit 50, both sources): 100 jobs, top match Practo 90/100 — logic same hai.

Error paths bhi check kiye: unsupported file → 400, chhota JD → 400, galat Apify token → stream me error event (crash nahi).
