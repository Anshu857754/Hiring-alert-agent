# Hiring Agent

Job description daalo (ya PDF upload karo) → AI usse search query banata hai → LinkedIn + Indeed scrape hote hain → har job ko JD ke against 0-100 match score milta hai → sorted table.

Backend **FastAPI (Python)**, frontend **React + Tailwind + Lucide** — sab CDN se aata hai, **koi build step nahi** (na npm install, na bundler). Poora UI ek hi file `public/index.html` me hai.

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
| `public/index.html` | **Poora frontend** — React app (single-file), Tailwind theme, JD attach bar, NDJSON stream, table sort/filter/CSV |
| `scrape-jobs.js` | Purana Node CLI — sirf scraping ke liye, abhi bhi chalta hai |

**Note:** `server.js` purana Express backend hai. Ab use karne ki zaroorat nahi — naya UI `/api/extract` aur `/api/health` use karta hai jo usme nahi hain, isliye `npm start` par PDF upload kaam nahi karega. `python run.py` hi chalao.

---

## API

| Endpoint | Kya karta hai |
|---|---|
| `GET /api/health` | model name + `.env` me keys hain ya nahi |
| `POST /api/extract` | multipart `file` → `{ text, chars, words, filename }` |
| `POST /api/search` | `{ jobDescription, limit, source, useAi }` → NDJSON stream |
| `POST /api/recommend` | `{ profile, jobs }` → `{ plan, usage, model }` — skill gaps + 15/30 din ka plan |

`/api/search` ke stream events:

```
{"type":"progress","stage":"parse|scrape|linkedin|indeed|score","message":"...","isError":false}
{"type":"params","params":{...},"limit":50}
{"type":"done","jobs":[...],"params":{...},"usage":{...},"model":"..."}
{"type":"error","message":"..."}
```

---

## PDF / DOCX upload (markitdown)

Alag upload tab nahi hai — JD input ke **neeche hi ek attach bar** hai ("Drop JD file (PDF, DOCX) or click to browse"). Click karke file chuno, ya file ko seedha JD box par drop kar do.

- Backend `markitdown` se text nikaalta hai — **poora local**, koi API call nahi, koi token cost nahi. Isiliye Gemini/GPT se PDF padhwane wala jugaad nahi kiya.
- Support: `.pdf` `.docx` `.doc` `.pptx` `.txt` `.md` `.html` `.htm` `.rtf` — max **10 MB**
- Nikla hua text seedha JD box me bhar jaata hai, wahin edit bhi kar sakte ho — search wahi final text use karti hai. Attach bar me file name + chars/words dikhta hai, "✕" se saaf ho jaata hai.
- **Scanned PDF (sirf images) me text nahi milega** — markitdown OCR nahi karta, aisi file par saaf error dikhega.

markitdown blocking library hai, isliye use `asyncio.to_thread` me chalate hain taaki bada PDF server ko block na kare.

---

## Design system

Saare colors **CSS custom properties** hain, `public/index.html` ke `<style>` block me — ek `:root[data-theme='light']` aur ek `:root[data-theme='dark']`. Tailwind ki har color utility inhi tokens par map hoti hai (`bg-surface`, `text-fg-muted`, `border-line`, `bg-brand-subtle`...), isliye component me koi raw hex nahi hai aur theme badalne par kuch peeche nahi chhootta.

**Brand: deep indigo** (`#4F46E5` light / `#818CF8` dark), electric-blue family ke saath. Indigo sirf in jagah reserved hai: primary CTA, active navigation, focus states, selected states, aur section indicators. Baaki UI neutral slate par chalti hai — product colorful nahi, **contrast-driven** hai.

Token groups: backgrounds (`--bg-app`, `--bg-sidebar`, `--surface`, `--surface-elev`, `--surface-hover`, `--surface-sunken`, `--surface-selected`, `--input-bg`), borders (`--border-subtle/-/-strong/-control`), text (`--text-primary/secondary/muted/disabled/inverse`), brand (5 shades + `--brand-on`), semantic (success/warning/error/info × default/subtle/border/text), focus, elevation.

### Contrast

WCAG 2.2 AA ko engineering requirement ki tarah treat kiya hai — **66 pairs measure kiye gaye hain**, guess nahi. Notable:

| Pair | Light | Dark |
|---|---|---|
| Muted text on surface | 4.76:1 | 6.92:1 |
| Muted text on app bg | 4.55:1 | 7.34:1 |
| CTA label on brand button | 6.29:1 | 6.31:1 |
| Active nav text on selected surface | 7.07:1 | 8.02:1 |
| Error text on error-subtle | 5.91:1 | 9.09:1 |
| Control boundary vs surface (UI, 3:1) | 4.76:1 | 6.92:1 |

Do jagah palette ko accessibility ke liye split karna pada:

- **`--border-strong` vs `--border-control`.** `#CBD5E1` decorative borders ke liye theek hai par toggle-off aur unchecked checkbox ka wahi ek visual boundary hai — `#CBD5E1` sirf 1.5:1 deta hai. Un control boundaries ke liye alag `--border-control` (`#64748B`) hai jo 4.76:1 deta hai.
- **Semantic base vs text.** `#059669` / `#D97706` indicators ke liye theek hain (3:1 chahiye) par normal text ke liye fail karte hain. Isliye har semantic ka ek `-text` variant hai (`#047857` / `#B45309`) jo 4.5:1 clear karta hai.

**Ek combo banned hai:** muted text on selected surface. Selected surfaces sirf `brand-text` ya `secondary` text carry karte hain — validator yahi rule assert karta hai.

### Structure borders se aati hai, luminance se nahi

Ye ek galti thi jo theek karni padi. Jab UI "flat" lag rahi thi, pehle cards ko background se **lighter** kar diya gaya — nateeja ye hua ki cards bade gray-navy slabs ban gaye aur aur bura lagne laga.

Sahi tareeka wo hai jo Linear/Vercel use karte hain: canvas near-black rakho, cards sirf halka sa upar, aur separation **border** se do. Validator ke thresholds bhi isi hisaab se badle — surface jump ka minimum kam, border ka minimum zyada:

| Check | Dark | Light |
|---|---|---|
| Card lifts off app bg | 1.11:1 (min 1.05) | 1.04:1 |
| Border reads on card | **1.83:1** (min 1.75) | 1.30:1 |
| Border reads on app bg | **2.04:1** | 1.25:1 |

Palette navy se hoti hui **warm cream / stone** par pahunchi — pehle cold blue-gray tha jo sakht lagta tha. Light theme cream (`#F7F4EF` canvas, white cards), dark theme warm charcoal (`#0B0A09` / `#1A1815`). Shadows bhi warm hain (`rgba(41,33,24,…)`) — cream ke upar neutral gray shadow ganda lagta hai. Rang sirf accent ke liye bacha hai.

**Meaning kabhi sirf rang se nahi jaati:** toggle ke knob me check/cross icon hai + bagal me "On"/"Off" text; score ke saath hamesha band label ("Strong match"); har toast me icon + screen-reader ke liye status word; low credits par warning icon + "Low credits" text.

### Theme toggle

Header me day/night switch (☀ / ☾) — thumb slide karta hai, active side ka symbol highlight hota hai. Pehli baar `prefers-color-scheme` follow karta hai, choose karne par `localStorage` me save ho jaata hai. `<head>` me ek inline script paint se pehle attribute set kar deta hai, isliye flash nahi hota.

**Light tokens bare `:root` par hain**, `[data-theme='light']` par nahi. Dark unhe override karta hai. Iska matlab `data-theme` kabhi missing ya corrupt ho jaaye to bhi page tokenless (colorless) nahi ho sakta — pehle exactly wahi bug tha: `store.set` JSON.stringify karta hai to localStorage me `"dark"` quotes ke saath jaata tha, head script usse raw padh ke `data-theme='"dark"'` set kar deta tha, aur koi selector match na hone se saare colors gayab ho jaate the. Head script ab value ko parse + validate karta hai.

---

## UI

SaaS app shell hai — left sidebar + top header + scrollable content. Main workflow ek hi page par 3 numbered steps me hai: **JD → configuration → pipeline**.

### New Search (main workflow)

- **Step 1 — Job Description** — bada textarea. Paste karo, ya neeche wali bar se PDF/DOCX upload karo / seedha drop kar do (minimum 20 characters). File lagne par compact chip dikhta hai: icon + filename + size + words + remove
- **"Load sample JD"** — ek click me demo JD, testing ke liye
- **Step 2 — Search configuration** — teen controls:
  - *Jobs to find*: `−  10  +` stepper (10–30, step 5, per source), neeche live `Estimated search cost: ~$0.05`
  - *Job sources*: multi-select dropdown, selected sources chips ki tarah dikhte hain. **Glassdoor aur Wellfound disabled ("Soon") hain** — backend abhi sirf LinkedIn + Indeed support karta hai
  - *AI scoring & ranking*: toggle. Off karoge to scraping hogi par score nahi milega (OpenRouter cost bhi nahi)
- **CTA "✨ Find candidates"** — ek hi primary button. Chalte waqt label asli stream stages follow karta hai: *Reading job description… → Searching candidates… → Ranking results…*
- **Step 3 — Candidate pipeline** — chalte waqt skeleton rows, phir ranked list. Har row me: match % + band label ("Strong match") + progress bar, role title, source badge, company/location/type/level/salary/posted, **matched skill tags**, AI summary, aur Save + View posting buttons
- Pipeline controls: search box, sort (relevance / recent / company / role), source filter, score filter, CSV export

### Career recommendations (default OFF)

Resume ya profile JD box me daalo, search chalao, aur ye feature near-miss roles ko **study plan** me badal deta hai.

- Config me chautha toggle — **default off**, jaise maanga tha. AI scoring off ho to ye bhi auto-disable ho jaata hai (bina score ke gap nikaalna possible hi nahi)
- On karne par bottom-right corner me **Kai** naam ka chhota launcher aata hai (career coach agent) — uspe near-miss roles ka count badge dikhta hai. Click karo to chat-style panel khulta hai; Escape ya ✕ se band. Plan tabhi banta hai jab **Build my plan** dabao — bina poochhe tokens kharch nahi hote
- Agent ka naam `AGENT_NAME` constant me hai (`public/index.html`), badalna ek line ka kaam hai
- Plan me: summary, **already in your favour** (strengths), **what is holding you back** (har gap ke saath kitni postings me maanga gaya), **timeline** (Day 1–7, 8–14…), **roles this opens up** (`71% → 85%` ke saath), aur **out of reach for now**
- **Plan ki lambai model khud decide karta hai** — 15 din agar gaps chhote hain (ek framework/tool), 30 din agar gehre hain (nayi language, distributed systems, cloud)
- Near-miss = 40–75 score. Isse upar wale already match karte hain, neeche wale alag career track hain
- Model ko **sirf un skills** ki ijaazat hai jo actually postings me likhi hain — invent nahi kar sakta. Aur jo role realistically 15/30 din me nahi khulega (jaise 10+ saal maangne wala Staff role) usse `notRealistic` me daalna padta hai, jhoota promise nahi

Ek live run: **~10s, ~$0.0007** (1,419 tokens). Apify credits bilkul nahi lagte — ye poora OpenRouter par hai.

---

## Latency

`deepseek/deepseek-v4-pro` reasoning model hai. Default me wo output ka **~75% andar hi andar sochne** me laga deta hai, aur wo hidden tokens bhi utna hi time lete hain. Cache-free benchmark (har call me alag nonce, warna repeat prompt cache hit deta hai aur timing jhoothi lagti hai):

| Setting | completion tokens | reasoning tokens |
|---|---|---|
| baseline | 3,102 | 2,353 |
| `reasoning_effort: "low"` | 3,440 | 2,680 — **asar nahi padta** |
| `reasoning: {max_tokens: 150}` | 5,287 | 4,654 — **cap ignore ho jaata hai** |
| **`reasoning: {enabled: false}`** | **654** | **0** |

Model ~70–95 tok/s deta hai, to token count hi wall-clock time hai. Yahan ke teeno kaam (JD parse, rubric scoring, plan) structured output hain — chain-of-thought inke liye zaroori nahi, aur JSON schema dono soorat me valid rehta hai.

Iska asar:

| | Pehle | Ab |
|---|---|---|
| Kai ka plan | 36–128s (bahut variance) | **~10s** |
| 20 jobs score karna | ~30s+ | **12.2s** |
| Plan ka kharcha | $0.0027 | **$0.0007** |

Do aur cheezein:

- **Partial results.** Scraping khatam hote hi unscored jobs stream par bhej dete hain (`{"type":"partial"}`), to table turant bhar jaata hai aur scores baad me aa jaate hain. Pehle poori scoring khatam hone tak skeleton hi dikhta tha.
- **Batch size 15 → 10.** Batches parallel chalte hain, to wall-clock time sabse dheeme *single* call se bandha hota hai — chhota batch matlab wo call chhoti.

### Baaki views (sidebar)

Ye sab **localStorage** par chalte hain, koi extra backend nahi:

| View | Kya dikhata hai |
|---|---|
| Overview | Stat tiles (searches run, roles matched, average match, estimated spend) + recent searches |
| Searches | Purani runs (last 10). "Open results" se wo pipeline wapas khul jaata hai |
| Matches | Aakhri search ka poora pipeline |
| Saved | Jo roles shortlist kiye |

- **Matched skill tags** LLM se nahi aate — backend per-job skills deta hi nahi. Ye client side derive hote hain: `params.mustHaveSkills` me se wahi dikhte hain jo posting ke title/description me actually milte hain
- **Credits indicator** local estimate hai (`jobs × $0.0026` jod ke), asli Apify balance nahi
- **Toasts** — file parse, save, CSV export, aur har error ke liye
- **Startup par keys check** — `.env` me key missing ho to red toast aata hai
- Responsive: tablet/mobile par sidebar drawer ban jaata hai, config controls stack ho jaate hain, CTA full width

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
- **Purana `node server.js` port 3000 par mat chhodna.** Wo `::` (sab interfaces) par bind hota hai aur uvicorn `127.0.0.1` par — browser me `localhost` pehle IPv6 par jaata hai, to purana Express backend khul jaata hai aur PDF upload `Cannot POST /api/extract` deta hai. Kaun sun raha hai check karne ke liye:
  ```powershell
  Get-NetTCPConnection -LocalPort 3000 -State Listen
  ```
- **Frontend ko pehli baar load karne me internet chahiye.** React, Tailwind, Babel, Lucide aur Inter font CDN se aate hain (unpkg + esm.sh + Google Fonts) — build step bachane ke liye. Browser inhe cache kar leta hai, par bilkul offline chalana ho to ye files `public/vendor/` me download karke `index.html` me paths badal dena.
- Tailwind ka Play CDN console me "should not be used in production" warning deta hai — local tool ke liye ye expected hai, ignore kar do.
- `.env` `.gitignore` me hai — commit mat karna.

### Scoring thodi strict hai

Bahut saari postings ke description me tech stack likha hi nahi hota. AI usse "detail missing" maan ke 10-15 point kaat deta hai — test run me top match ko 89 mila kyunki JD ka PostgreSQL/AWS posting me mention hi nahi tha.

Zyada naram scoring chahiye to [app/llm.py](app/llm.py) ke `SCORE_PROMPT` me ek line add kar do:

```
Missing details are not a mismatch — only deduct for clear contradictions
(different role, different seniority, different tech stack).
```

Ulta strict chahiye (sirf perfect matches upar) to scoring guide ke thresholds badha do.

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
