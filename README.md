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

`.env` me sirf do cheezein zaroori hain — **API keys ab yahan nahi aati**, wo
har user Settings me khud daalta hai (dekho *Accounts* section):

```
DATABASE_URL=postgresql://user:pass@host.neon.tech/neondb?sslmode=require
APP_SECRET_KEY=        # users ki keys + LinkedIn cookie isse encrypt hoti hain

COOKIE_SECURE=0             # https deploy par 1 kar do
FOUNDER_MAX_EMPLOYEES=50    # optional — isse chhoti company me founder/CTO, badi me HR
CONNECT_PROVIDER=apify      # optional — apify ya unipile

# Forgot password ke liye (dekho *Forgot password* section)
APP_BASE_URL=http://localhost:10000
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tumhara@gmail.com
SMTP_PASS=                  # Gmail ka **app password**, normal password nahi
```

`APP_SECRET_KEY` koi bhi lambi random string ho sakti hai:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Badal di to purani sealed keys/cookies bekaar ho jaayengi — UI unhe dobara
maangega, crash nahi hoga.

`DATABASE_URL` ke bina ab app kaam nahi karegi: accounts hi database me rehte
hain, aur bina account ke koi screen nahi khulti. (Pehle DB optional thi.)

Install aur run (Python 3.10+):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python run.py
```

Phir browser me kholo: **http://localhost:10000**  (ya jo `PORT` set kiya ho)

Migrations server start hote hi apne aap chal jaati hain. Alag se chalana ho
(deploy/CI) to:

```bash
python migrate.py            # pending migrations apply
python migrate.py --status   # kya baaki hai
python migrate.py --reset --yes   # hiring_agent schema gira kar naye sire se
```

Dev me auto-reload chahiye to:

```bash
uvicorn app.main:app --reload --port 10000
```

---

## Accounts (multi-user)

Pehle ye app single-user thi: ek `.env`, ek banda, aur ek HTTP Basic password
gate. Ab har banda apna account banata hai, apni API keys deta hai, aur sirf
apna data dekhta hai.

**Signup / login**

- Bina login ke sirf login screen dikhti hai. `GET /api/auth/me` `null` de to
  frontend wahin ruk jaata hai — koi data fetch hota hi nahi
- Password `hashlib.scrypt` se hash hota hai (stdlib, memory-hard). Har user ka
  apna salt; compare `hmac.compare_digest` se — galat password ka jawab hamesha
  ek jitna time leta hai
- Session server-side hai (`sessions` table) + httpOnly cookie. Logout row
  delete karta hai, matlab token sach me mar jaata hai. Signed cookie hoti to
  logout sirf browser se cookie hataata
- Email na mile tab bhi ek dummy hash chalta hai — warna response time se pata
  chal jaata ki ye email registered hai ya nahi

**Har user apni keys laata hai**

Settings → **Your API keys** me Apify aur OpenRouter keys daalo. Ye Fernet se
sealed hoti hain (`APP_SECRET_KEY`) aur browser ko kabhi wapas nahi jaati —
UI sirf "set hai / nahi hai" dekhta hai.

Server ki `.env` wali keys ab kisi user ko nahi milti. Wajah seedhi hai: agar
milti, to pehla ajnabi jo signup karta wo tumhare Apify credits jalata. Isliye
keys ke bina search/draft/discover sab saaf error deta hai, chalta nahi.

**Data isolation**

Har table par `user_id` hai aur har query uske andar bandhi hai. Sirf list
queries nahi — ID se bhi kuch nahi milta:

| Bob ne try kiya | Nateeja |
|---|---|
| `GET /api/searches/{alice_ki_id}` | 404 |
| `DELETE /api/searches/{alice_ki_id}` | 404 |
| `POST /api/senders/{alice_ki_id}/verify` | 404 |
| `DELETE /api/contacts/{alice_ki_id}` | `deleted: 0` |
| `POST /api/connect/send` Alice ke contacts par | `sent: 0` — Apify call hui hi nahi |

Unique constraints bhi per-user hain (`(user_id, job_key)`,
`(user_id, profile_url)`), warna do bande ek hi job save nahi kar paate.

**Purana data**

Multi-user se pehle ki rows ka `user_id` NULL hai. **Pehla signup** unhe adopt
kar leta hai (`users.adopt_orphans`) — isliye apna account sabse pehle banao,
warna tumhari history kisi aur ke paas chali jaayegi.

**Deploy par**

`COOKIE_SECURE=1` set karo — warna session cookie plain http par bhi jaayegi.
`APP_SECRET_KEY` set na ho to koi user apni keys hi save nahi kar paayega.

---

## Forgot password

Password scrypt se hashed hai — recover karne ka koi raasta hai hi nahi, sirf
reset. Login screen par **Forgot password?** se flow shuru hota hai.

```
email daalo  →  POST /api/auth/forgot  →  token banta hai (32 random bytes)
             →  email me link:  {APP_BASE_URL}/?reset=<token>
link kholo   →  GET  /api/auth/reset?token=…   (valid hai ya nahi)
naya password→  POST /api/auth/reset            (token jal jaata hai)
```

**Teen cheezein jaan-boojh kar aisi hain:**

| Kya | Kyun |
|---|---|
| DB me token ka **sha256** hai, raw token nahi | DB dump leak ho jaaye to bhi koi link banake kisi ka account nahi khol sakta — wahi soch jo password hashing ke peeche hai |
| Jawab hamesha `"If that email has an account…"` | Warna ye route email checker ban jaata: 200 matlab registered, 404 matlab nahi |
| Link response me kabhi nahi, sirf email me | Browser me dikha dete to koi bhi ajnabi kisi ka bhi email daal ke uska password badal leta |

Uske alawa: token **30 minute** chalta hai (`RESET_TOKEN_MINUTES`), **ek hi
baar** chalta hai, naya request purane token maar deta hai, aur reset hote hi
us user ke **saare sessions** delete ho jaate hain. Ek email par har 60 second
me ek hi mail jaati hai — warna koi kisi ke inbox par button daba ke 500 mails
girwa deta. Purane/expired rows startup par saaf ho jaate hain.

**SMTP setup (Gmail)**

1. Google account par 2FA on karo
2. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) se 16-character app password banao — tumhara **normal Gmail password kaam nahi karega**
3. `.env` me daalo:

```
APP_BASE_URL=https://tumhara-app.onrender.com   # deploy par asli URL, warna email me localhost jaayega
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tumhara@gmail.com
SMTP_PASS=abcd efgh ijkl mnop
SMTP_FROM=tumhara@gmail.com
SMTP_FROM_NAME=RAYN.AI
```

Port 465 use karna ho to `SMTP_SSL=1` — 587 par STARTTLS apne aap lagta hai.

**SMTP set na ho to?** App phir bhi chalti hai. Reset link server ke log me
print hota hai (`WARNING … password reset link for x@y.com: …`) aur user ko
wahi generic message dikhta hai. UI bhi bata deta hai ki mail nahi nikli.
Matlab admin manually link bhej sakta hai, par email ke bina ye feature
end-users ke liye adhoora hai — deploy se pehle SMTP zaroor bhar do.

---

## Public demo

LinkedIn par link share karna ho to problem ye thi: har visitor se apni Apify
aur OpenRouter key maangi jaati hai. Recruiter ke paas Apify account hota nahi
— wo Settings dekh kar chala jaata.

Ab login screen par **"Try the demo — no sign-up"** hai. Ek click me banda
`demo@rayn.ai` account me chala jaata hai jahan ek asli purana run pada hai:
163 scraped jobs, match scores, 6 decision makers, 8 outreach drafts, 2
learning plans.

**Read-only kaise banaya:** frontend par button disable karna kaafi nahi tha —
koi bhi seedha API hit kar ke Apify credits jala sakta tha, ya sabke liye rakha
demo data delete kar sakta tha. Isliye asli rok server par hai. Jo bhi route
paisa kharch karta hai ya data badalta hai, wo ab `writable_user` dependency se
hoke jaata hai (`app/main.py`), aur demo account ko wahin 403 mil jaata hai:

| Band (403) | Khula (200) |
|---|---|
| `POST /api/search`, `/api/recommend`, `/api/outreach` | saare `GET` — searches, jobs, contacts, outreach, stats |
| `POST /api/contacts/discover`, `/api/connect/send` | `POST /api/extract` (PDF parse — local hai, free hai) |
| `POST /api/auth/keys`, `/api/auth/password`, `/api/senders` | |
| saare `DELETE` | |

UI me bhi: demo banner upar, Launch button "Demo — read only" (disabled), aur
"Clear history" gayab.

**Demo me data bharna:**

```bash
python seed_demo.py anshu.singh8595508@gmail.com
```

Jis account se copy karna hai wo argument me. Har baar chalane par demo ka
purana data hata kar naya bharta hai, to baar-baar chalana safe hai. Sender
account copy nahi hota — usme sealed LinkedIn cookie hoti hai.

`DEMO_ENABLED=0` se demo band ho jaata hai, `DEMO_EMAIL` se account ka email
badal sakte ho.

**Demo ko koi env var nahi chahiye** — `APP_SECRET_KEY` na bhi ho to chalta
hai, kyunki demo me koi key encrypt hoti hi nahi. Jo banda apni keys daal kar
live chalana chahe, uske liye `APP_SECRET_KEY` zaroori hai.

---

## Files

| File | Kaam |
|---|---|
| `run.py` | Entry point — `0.0.0.0` par bind karta hai, port `$PORT` (default 10000) |
| `app/main.py` | FastAPI app. `POST /api/search` NDJSON stream, `POST /api/extract` file→text, `GET /api/health` |
| `app/llm.py` | OpenRouter calls — `deepseek/deepseek-v4-pro`. Do kaam: JD parse karna + jobs ko score karna |
| `app/apify.py` | Dono scrapers chalata hai, output normalize karta hai, duplicates hatata hai |
| `app/outreach.py` | Founder-ya-HR ka rule + LinkedIn people-search link. Threshold `config.FOUNDER_MAX_EMPLOYEES` |
| `app/people.py` | Company ke decision makers Apify se — bucket ke titles, aur `works_at()` company filter |
| `app/connect.py` | Connection request bhejna. Provider interface (apify / unipile) + rate limiting + cookie verify |
| `app/crypto.py` | Sender cookie ko Fernet se seal/unseal karta hai. Key: `APP_SECRET_KEY` |
| `app/docs.py` | markitdown wrapper — PDF/DOCX se text nikaalta hai (local, koi LLM call nahi) |
| `app/db.py` | Postgres connection pool + migration runner (`migrations/*.sql`) |
| `app/store.py` | Saari DB queries — searches, jobs, saved_jobs, plans, outreach, contacts, senders, stats |
| `app/config.py` | `.env` load, limits, allowed file types, `DATABASE_URL`, `APP_PASSWORD` |
| `app/users.py` | Accounts, scrypt passwords, server-side sessions, per-user API keys, reset tokens |
| `app/mailer.py` | SMTP se email (abhi sirf password reset). SMTP na ho to link server log me |
| `seed_demo.py` | Demo account me showcase data bharta hai (ek asli run ki copy) |
| `migrate.py` | Migrations alag se chalane ka CLI |
| `migrations/*.sql` | Schema. File ka number hi version hai (`0001_init.sql` → 1) |
| `public/index.html` | **Poora frontend** — React app (single-file), Tailwind theme, JD attach bar, NDJSON stream, table sort/filter/CSV |
| `scrape-jobs.js` | Purana Node CLI — sirf scraping ke liye, abhi bhi chalta hai |

**Note:** `server.js` purana Express backend hai. Ab use karne ki zaroorat nahi — naya UI `/api/extract` aur `/api/health` use karta hai jo usme nahi hain, isliye `npm start` par PDF upload kaam nahi karega. `python run.py` hi chalao.

---

## API

| Endpoint | Kya karta hai |
|---|---|
| `GET /api/health` | Public. Model name, `secretReady`, DB status. Koi user data nahi |
| `POST /api/extract` | multipart `file` → `{ text, chars, words, filename }` |
| `POST /api/search` | `{ jobDescription, limit, source, useAi, titleOverride }` → NDJSON stream (run DB me save hoti hai). `titleOverride` set ho to wahi scrape keyword banta hai, model ka guess nahi |
| `POST /api/recommend` | `{ profile, jobs, searchId }` → `{ plan, usage, model }` — skill gaps + 15/30 din ka plan |
| `POST /api/outreach` | `{ job, profile, searchId }` → `{ draft, key, model }` — kis tak pahunchna hai + likha hua message |
| `GET /api/outreach` | `?searchId=12` → us run ke saare drafts, `job_key` se keyed |
| `GET /api/searches` | `?limit=25&all=false` → history list (DB se) |
| `GET /api/searches/{id}` | Ek run poori wapas — JD, params, jobs aur plan |
| `DELETE /api/searches/{id}` | Ek run hatao (jobs cascade ho jaati hain) |
| `DELETE /api/searches` | Poori history saaf |
| `GET /api/saved` | Shortlist |
| `POST /api/saved` | `{ job, searchId }` → shortlist me daalo (url par dedupe) |
| `DELETE /api/saved?key=<job url>` | Shortlist se hatao |
| `GET /api/stats` | Overview ke tiles — searches, roles, spend, average match |
| `POST /api/import` | Purana localStorage data ek baar DB me — UI khud call karta hai |
| `POST /api/auth/signup` | `{ email, password, name? }` → account + session cookie. Pehla user orphan rows adopt karta hai |
| `POST /api/auth/login` | `{ email, password }` → session cookie |
| `POST /api/auth/logout` | Session row delete — token sach me mar jaata hai |
| `GET /api/auth/me` | `{ user }` ya `{ user: null }`. Frontend boot par yahi poochta hai |
| `POST /api/auth/password` | `{ current, new }` → password badlo (baaki sab sessions gir jaate hain) |
| `POST /api/auth/forgot` | `{ email }` → reset link email par. Jawab hamesha ek jaisa, chahe email registered ho ya na ho |
| `GET /api/auth/reset?token=` | Link valid hai ya nahi — form dikhane se pehle frontend yahi poochta hai |
| `POST /api/auth/reset` | `{ token, password }` → naya password. Token ek hi baar chalta hai, saare sessions gir jaate hain |
| `POST /api/auth/keys` | `{ apify?, openRouter? }` → apni keys save karo (sealed). `null` = mat chhedo, `""` = hata do |
| `GET /api/senders` | Sender accounts + `secretReady`. **Cookie kabhi wapas nahi aati** — sirf `hasCookie` |
| `POST /api/senders` | `{ id?, label, liAt, jsessionid?, isPremium }` → cookie encrypt ho kar save. `liAt` khaali = purani cookie waise hi rehti hai |
| `POST /api/senders/{id}/verify` | Ek GET se dekhta hai cookie zinda hai ya nahi → `ready` / `expired` / `unknown`. Koi invite nahi jaata |
| `POST /api/senders/{id}/default` | Is account ko default sender banao |
| `DELETE /api/senders/{id}` | Account + uski sealed cookie mita do |
| `GET /api/contacts` | `?jobKey=...` → mile hue decision makers, har ek ka latest request status ke saath |
| `POST /api/contacts/discover` | `{ job, target?, employees?, limit }` → company ke founder/CTO ya HR (cookie nahi chahiye) |
| `DELETE /api/contacts/{id}` | Ek contact hatao |
| `POST /api/connect/send` | `{ contactIds, notes, senderId? }` → NDJSON stream. Ek baar me max 10, beech me ~25s gap |

`/api/search` ke stream events:

```
{"type":"search","searchId":12,"cost":0.052}
{"type":"progress","stage":"parse|scrape|linkedin|indeed|score","message":"...","isError":false}
{"type":"params","params":{...},"limit":50}
{"type":"partial","jobs":[...],"params":{...}}
{"type":"done","searchId":12,"jobs":[...],"params":{...},"usage":{...},"model":"..."}
{"type":"error","message":"..."}
```

`/api/connect/send` ke stream events:

```
{"type":"start","count":5,"noteLimit":200}
{"type":"sending","contactId":12,"name":"..."}
{"type":"waiting","contactId":13,"seconds":27}
{"type":"result","contactId":12,"status":"sent|failed","error":null,"runUrl":"..."}
{"type":"skipped","contactId":14,"name":"...","reason":"Already invited"}
{"type":"done","sent":4,"failed":1,"results":[...]}
```

---

## Database (Neon Postgres)

Pehle history aur shortlist browser ke `localStorage` me the — dusre browser me
kholo to sab gayab. Ab sab Postgres me hai; `localStorage` me sirf theme aur
"import ho chuka" wala flag bacha hai.

**Schema `hiring_agent`** — ye Neon database dusre project ke saath share hota
hai (uski tables `public` me hain, unka apna `alembic_version` bhi wahin hai).
Naam takraane se bachne ke liye hamari tables alag schema me banti hain.
`DB_SCHEMA` env var se badla ja sakta hai.

| Table | Kya rakhti hai |
|---|---|
| `searches` | Har run — JD, params, source, limit, status, cost, token usage |
| `jobs` | Us run ki postings + `match_score` / `match_reason`. `(search_id, job_key)` unique |
| `saved_jobs` | Shortlist. `job_key` (url) unique — ek posting do baar save nahi hoti |
| `plans` | `/api/recommend` ka 15/30 din wala plan, search se juda hua |
| `outreach` | Reach-out drafts — company size, founder/HR target, message. Append-only, latest padha jaata hai |
| `schema_migrations` | Kaunsi migration lag chuki hai |

Kuch cheezein jaan-boojh kar aise hain:

- **Table names hamesha schema ke saath likhe jaate hain** (`"hiring_agent".jobs`),
  `search_path` par bharosa nahi. Neon ka `-pooler` endpoint pgbouncer transaction
  mode me chalta hai — wahan har transaction alag server connection par ja sakti
  hai aur session ka `SET search_path` gayab ho jaata hai.
- **psycopg ka sync pool + `asyncio.to_thread`**, async mode nahi. Windows par
  uvicorn ProactorEventLoop banata hai jispar psycopg async chalta hi nahi.
- **Search row pehle banti hai, baad me bharti hai.** Isliye beech me band hui
  run `cancelled` aur fail hui run `error` status ke saath dikh jaati hai.
  Server restart par purani `running` rows `interrupted` mark ho jaati hain.
- **DB down ho to app chalti rehti hai** — search aur scoring waise hi chalte
  hain, bas save nahi hota aur header me "DB offline" chip aa jaati hai.

Nayi migration add karni ho to `migrations/0002_kuch.sql` bana do — server agli
baar start hote hi use apply kar dega.

---

## Deploy (Render)

`/api/search` ek NDJSON stream hai jo scrape + scoring ke dauraan **1-3 minute
tak khuli rehti hai**. Isliye serverless (Vercel Hobby ka 60s function limit)
yahan nahi chalega — normal long-running container chahiye. Render ya Railway
theek hain; DB already Neon par hai, to sirf app process host karna hai.

Render par **New → Web Service**, repo connect karo, phir:

| Setting | Value |
|---|---|
| Language | **Python 3** — dhyan se chuno, root me purana `package.json`/`server.js` pada hai jise dekh kar Render Node detect kar sakta hai |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python run.py` |

Environment variables: `DATABASE_URL` (Neon ka **pooled** `-pooler` wala URL),
`APP_SECRET_KEY`, aur `COOKIE_SECURE=1`. API keys ab per-user hain, isliye
server par `APIFY_API_KEY`/`OPENROUTER_API_KEY` ki zaroorat nahi.

Forgot password chahiye to `APP_BASE_URL` (asli https URL) + `SMTP_*` bhi
set karo — dekho *Forgot password* section.

Do cheezein jaan-boojh kar aise hain:

- `run.py` `0.0.0.0` par bind karta hai aur `$PORT` uthata hai — container ke
  bahar se connect karne ke liye dono zaroori hain. `127.0.0.1` par bind karoge
  to host tumhari app tak pahunch hi nahi paayega.
- `.python-version` me `3.12` pin hai. Bina pin ke host koi bhi version utha
  leta hai aur `psycopg-binary` / `markitdown` ke wheels miss ho sakte hain.

Migrations pehli deploy par khud chal jaati hain — logs me
`migrations applied: 0001_init.sql` dikhega. Alag se koi step nahi.

**`APP_SECRET_KEY` aur `COOKIE_SECURE=1` zaroor set karo.** (Purana `APP_PASSWORD`
gate hat chuka hai — ab accounts hain.) Bina secret key ke koi user apni keys
save nahi kar paayega. Pehle ye padho: URL jisko bhi mila wo signup kar
kar tumhare Apify credits aur OpenRouter tokens jala sakta hai. Set karte hi
browser khud username/password maangta hai (user default `admin`, `APP_USERNAME`
se badal sakte ho). Sirf `/api/health` khula rehta hai taaki host ka uptime check
chalta rahe — usme koi key ya DB detail nahi jaati.

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

> **Note (RAYN.AI redesign):** UI ab dark-first hai — canvas `#0B0F17`, cards `#111625` + `border-white/10`,
> accent indigo→violet gradient, active/enabled ke liye emerald `#10B981`. Token *structure* neeche wali
> hi hai (wahi naam, wahi Tailwind mapping), par values badal gayi hain aur ab dark default hai.
> Neeche ke contrast numbers purane cream/near-black palette ke hain — unhe dobara measure karna baaki hai.

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

> **Note (RAYN.AI redesign):** shell wahi hai, par nav ab 8 items ka hai — Overview, New Search, Pipeline,
> Talent Pool, Saved Matches, Outreach, Analytics, Settings — sidebar collapse hota hai, top bar me
> ⌘K command palette + model pill + credits meter hai, aur New Search ke teen numbered steps ki jagah ab
> **AI Prompt Studio** (3 tabs) + **bento configuration** (2 cards) + **floating glass action dock** hai.
> Neeche wala step-by-step description purane layout ka hai.

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

### Reach out — founder ya HR (Contacts)

Job mil gayi, ab uske andar kis insaan ko likhna hai? Rule seedha hai aur code
me hai, model par nahi chhoda gaya (`app/outreach.py`):

| Company size | Kis tak jaana hai |
|---|---|
| `< FOUNDER_MAX_EMPLOYEES` (default **50**) | **Founder / CTO** — itni chhoti team me inbound founder khud padhta hai |
| `>= 50` | **HR / Recruiter** — is size par hiring TA team ke through hi chalti hai |
| size pata hi nahi chali | **HR** — bade organisation ke CEO ko DM karna ulta padta hai, isliye safer route |

- Har pipeline row par **Reach out** button. Dabate hi model (a) company kitni
  badi hai estimate karta hai, (b) usi hisaab se message likhta hai. Founder wala
  note aur HR wala note ek jaise nahi hote — founder ko *tumhare kaam se kya
  banega* chahiye, HR ko *requirements se kitna match karte ho*
- Faisla model ka nahi hai. Model sirf employees ka number deta hai; founder/HR
  `decide_target()` tay karta hai. Model ne kisi aur ko address kar diya to draft
  par saaf warning aati hai
- Draft me: target chip + wajah, size estimate aur uski confidence, **subject**,
  poora **message**, **LinkedIn connection note** (300 char limit ke saath), aur
  **follow-up** line — har block par copy button
- Draft ke saath ready-made LinkedIn people-search link bhi milta hai. Asli log
  chahiye to **Find people** — neeche "Decision makers" section dekho
- Sidebar me **Contacts** view — jitne drafts bane hain sab ek jagah, *All /
  Founders / HR* tabs ke saath. Drafts `outreach` table me search ke saath jude
  rehte hain, isliye purani run kholne par wapas aa jaate hain
- Message tumhare resume/profile se likha jaata hai (wahi text jo JD box me hai),
  isliye kam se kam 20 characters chahiye. Ek job ka draft ek hi baar banta hai —
  dobara chahiye to modal me **Redraft**

### Decision makers + connection requests

Draft ban gaya, ab us company me **asli log** kaun hain aur unhe invite kaise
bheje. Do alag cheezein hain, aur inki zarooratein bhi alag hain:

| Step | Cookie chahiye? | Kya lagta hai |
|---|---|---|
| **Find people** — company ke founder/CTO ya HR dhoondhna | ❌ nahi | Apify actor, public profile data, ~$0.002/profile |
| **Send request** — connection request + note bhejna | ✅ haan | LinkedIn `li_at` cookie + paid connect actor (ya Unipile) |

**Sender account (Settings me)**

- Settings → **LinkedIn sender account** → cookie paste karo. Browser me LinkedIn
  kholo → DevTools → Application → Cookies → linkedin.com → `li_at` ki value copy
- Cookie DB me **Fernet se encrypt** ho kar jaati hai (`app/crypto.py`), key
  `APP_SECRET_KEY` se banti hai. **Key set nahi hai to cookie save hi nahi hoti** —
  plain text me rakhne se behtar hai feature band rahe
- Cookie kabhi browser ko wapas nahi bheji jaati. Save ke baad field khaali hi
  dikhta hai; sirf "saved" badge se pata chalta hai
- **Check cookie** button ek GET karta hai (koi invite nahi jaata) aur batata hai
  cookie zinda hai ya expire ho chuki. Redirects follow hote hain — mari hui
  cookie par LinkedIn pehle `/feed/` ko 200 deta dikhta hai, asli login page do
  hop baad aata hai

**Bhejna (Outreach view)**

- Kisi bhi drafted company par **Find people** → mile hue log neeche table me
- Checkbox se 5–7 chuno, ek note likho, **Send N connection requests**
- Requests **ek-ek kar ke** jaati hain, beech me ~25s ka random gap. Das invite
  ek second me jaana LinkedIn ke liye sabse saaf bot signal hai
- Ek insaan ko dobara invite nahi jaata — `connection_requests` par partial
  unique index isko DB par hi rokta hai

**Limits — dhyan se padho**

- Ek send me **10** (`MAX_BATCH_INVITES`), ek din me **20**, ek hafte me **100**.
  LinkedIn ki apni limit ~100–200/week hai; hum uske aas-paas bhi nahi jaate
- Counter sirf **sach me gaye** invites par badhta hai, fail hue par nahi
- **Free LinkedIn account par note ~5/month par khatam ho jaata hai** aur 200
  char me katta hai (Premium: koi monthly cap nahi, 300 char). Iske baad invite
  jaata hai par note ke bina. UI Settings me ye warning dikhata hai
- Ye automation LinkedIn ke User Agreement §8.2 ke khilaf hai. Restriction jis
  account ki cookie hai usi par lagti hai

**Actor ki ek asli kami**

Default people actor (`apt_marble/...`) ek **keyword search** hai, company ka
roster nahi. "Zerodha" maango to duniya bhar ke founders aa jaate hain. Isliye
`app/people.py` ka `works_at()` har profile ko company ke against check karta
hai aur jo match na kare use **gira deta hai** — galat aadmi ko "aapki company
me role dekha" wala note bhejna sabse bura outcome hai.

Natija: is actor se aksar **0 results** aate hain. Sahi results chahiye to
company-roster wala actor lagao (rental chahiye):

```
PEOPLE_ACTOR=memo23/linkedin-company-people-scraper
```

`app/people.py` ka `_actor_input()` dono ko sambhalta hai. Naya actor lagana ho
to sirf wahan ek entry jodo.

**Bhejne ka provider**

`CONNECT_PROVIDER=apify` (default) ya `unipile`. Apify ke connect actors saste
hain par bharose ke laayak kam — store par inke success rate 0–44% dikhte hain,
aur zyadatar rental maangte hain. Unipile paid hai (~€40/mo) par asal me chalta
hai aur cookie unke paas rehti hai, hamare paas nahi. `app/connect.py` dono ko
ek interface ke peeche rakhta hai, isliye switch karna sirf env var badalna hai.

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

Ye sab **Postgres** se aate hain (`/api/searches`, `/api/saved`, `/api/stats`):

| View | Kya dikhata hai |
|---|---|
| Overview | Stat tiles (searches run, roles matched, average match, estimated spend) — ab all-time, DB se — + recent searches |
| Searches | Purani runs (last 50). "Open results" se JD, params, jobs aur plan sab wapas mil jaate hain; har row par delete bhi hai |
| Matches | Aakhri (ya jo khola) search ka poora pipeline |
| Saved | Jo roles shortlist kiye — `saved_jobs` table |

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
