-- Decision makers + unka connection request bhejne ka record.
--
-- Teen tables:
--   sender_accounts     — kis LinkedIn account se bhejna hai (cookie encrypted)
--   contacts            — Apify se nikale hue log, company ke hisaab se
--   connection_requests — kisko kya bheja, kab, aur kya hua
--
-- Cookie kabhi plain text me yahan nahi aati: app/crypto.py Fernet se seal
-- karta hai aur APP_SECRET_KEY ke bina wapas nahi khulti.

CREATE TABLE IF NOT EXISTS sender_accounts (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    label            TEXT         NOT NULL,
    provider         TEXT         NOT NULL DEFAULT 'apify',
    -- Fernet ciphertext. NULL matlab abhi tak cookie di hi nahi gayi.
    li_at_enc        TEXT,
    jsessionid_enc   TEXT,
    user_agent       TEXT,
    -- Premium account bina personalised note ke ~5/month par hi ruk jaata hai,
    -- isliye UI ko batana padta hai ki note bhejna safe hai ya nahi.
    is_premium       BOOLEAN      NOT NULL DEFAULT FALSE,
    is_default       BOOLEAN      NOT NULL DEFAULT FALSE,
    status           TEXT         NOT NULL DEFAULT 'unverified',
    status_detail    TEXT,
    last_verified_at TIMESTAMPTZ,
    -- Rate limit counters. week_start har Monday par reset hota hai.
    daily_cap        INTEGER      NOT NULL DEFAULT 20,
    weekly_cap       INTEGER      NOT NULL DEFAULT 100,
    sent_today       INTEGER      NOT NULL DEFAULT 0,
    day_start        DATE,
    sent_this_week   INTEGER      NOT NULL DEFAULT 0,
    week_start       DATE
);

-- Ek hi default sender rehna chahiye — partial unique index isko DB par hi pakadta hai.
CREATE UNIQUE INDEX IF NOT EXISTS sender_accounts_one_default
    ON sender_accounts (is_default) WHERE is_default;

CREATE TABLE IF NOT EXISTS contacts (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discovered_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    search_id      BIGINT       REFERENCES searches (id) ON DELETE SET NULL,
    job_key        TEXT,
    company        TEXT,
    full_name      TEXT         NOT NULL,
    headline       TEXT,
    role_title     TEXT,
    location       TEXT,
    profile_url    TEXT         NOT NULL,
    -- 'founder' ya 'hr' — wahi do buckets jo outreach.py use karta hai.
    target         TEXT,
    seniority      TEXT,
    employees      INTEGER,
    source         TEXT,
    CONSTRAINT contacts_profile_uniq UNIQUE (profile_url)
);

CREATE INDEX IF NOT EXISTS contacts_job_key_idx ON contacts (job_key);
CREATE INDEX IF NOT EXISTS contacts_company_idx ON contacts (company);
CREATE INDEX IF NOT EXISTS contacts_discovered_idx ON contacts (discovered_at DESC);

CREATE TABLE IF NOT EXISTS connection_requests (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at      TIMESTAMPTZ,
    contact_id   BIGINT       NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    sender_id    BIGINT       REFERENCES sender_accounts (id) ON DELETE SET NULL,
    provider     TEXT,
    note         TEXT,
    -- queued | sent | failed | skipped
    status       TEXT         NOT NULL DEFAULT 'queued',
    error        TEXT,
    run_url      TEXT
);

-- Ek hi bande ko dobara invite na chala jaye — UI isi se "already sent" dikhata hai.
CREATE UNIQUE INDEX IF NOT EXISTS connection_requests_sent_uniq
    ON connection_requests (contact_id) WHERE status IN ('queued', 'sent');

CREATE INDEX IF NOT EXISTS connection_requests_created_idx ON connection_requests (created_at DESC);
