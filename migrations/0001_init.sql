-- Hiring Agent ka base schema.
-- Sab kuch app.config.DB_SCHEMA (default: hiring_agent) ke andar banta hai —
-- runner har migration se pehle search_path set kar deta hai, isliye yahan
-- table names bina schema prefix ke likhe hain.

-- Ek search run = ek row. Jo bhi UI me "history" tha, ab yahan rehta hai.
CREATE TABLE IF NOT EXISTS searches (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT         NOT NULL DEFAULT 'running',
    job_description TEXT         NOT NULL,
    title           TEXT,
    location        TEXT,
    country         TEXT,
    source          TEXT         NOT NULL DEFAULT 'both',
    job_limit       INTEGER      NOT NULL DEFAULT 10,
    use_ai          BOOLEAN      NOT NULL DEFAULT TRUE,
    model           TEXT,
    params          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    usage           JSONB,
    job_count       INTEGER      NOT NULL DEFAULT 0,
    cost            NUMERIC(10,4) NOT NULL DEFAULT 0,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS searches_created_at_idx ON searches (created_at DESC);
CREATE INDEX IF NOT EXISTS searches_status_idx ON searches (status);

-- Har search ke scraped + scored postings.
CREATE TABLE IF NOT EXISTS jobs (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    search_id        BIGINT       NOT NULL REFERENCES searches (id) ON DELETE CASCADE,
    position         INTEGER      NOT NULL DEFAULT 0,
    job_key          TEXT         NOT NULL,
    source           TEXT,
    title            TEXT,
    company          TEXT,
    location         TEXT,
    posted_at        TEXT,
    contract_type    TEXT,
    experience_level TEXT,
    work_type        TEXT,
    salary           TEXT,
    url              TEXT,
    apply_url        TEXT,
    applicants       TEXT,
    description      TEXT,
    match_score      INTEGER,
    match_reason     TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT jobs_search_key_uniq UNIQUE (search_id, job_key)
);

CREATE INDEX IF NOT EXISTS jobs_search_id_idx ON jobs (search_id, position);
CREATE INDEX IF NOT EXISTS jobs_match_score_idx ON jobs (match_score DESC NULLS LAST);

-- Shortlist. job_key unique hai taaki ek posting do baar save na ho.
CREATE TABLE IF NOT EXISTS saved_jobs (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_key          TEXT         NOT NULL UNIQUE,
    search_id        BIGINT       REFERENCES searches (id) ON DELETE SET NULL,
    saved_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    source           TEXT,
    title            TEXT,
    company          TEXT,
    location         TEXT,
    posted_at        TEXT,
    contract_type    TEXT,
    experience_level TEXT,
    work_type        TEXT,
    salary           TEXT,
    url              TEXT,
    apply_url        TEXT,
    applicants       TEXT,
    match_score      INTEGER,
    match_reason     TEXT
);

CREATE INDEX IF NOT EXISTS saved_jobs_saved_at_idx ON saved_jobs (saved_at DESC);

-- /api/recommend ka 15/30 din wala plan.
CREATE TABLE IF NOT EXISTS plans (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    search_id   BIGINT       REFERENCES searches (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    profile     TEXT         NOT NULL,
    plan_days   INTEGER,
    model       TEXT,
    plan        JSONB        NOT NULL,
    usage       JSONB
);

CREATE INDEX IF NOT EXISTS plans_search_id_idx ON plans (search_id, created_at DESC);
