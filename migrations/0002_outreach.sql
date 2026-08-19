-- Reach-out drafts. Har posting ke liye: company kitni badi hai, kis tak
-- pahunchna hai (founder ya HR), aur bheja jaane wala message.
-- Plans ki tarah ye bhi append-only hai — dobara generate karo to nayi row
-- banti hai aur latest wali padhi jaati hai.

CREATE TABLE IF NOT EXISTS outreach (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    search_id        BIGINT       REFERENCES searches (id) ON DELETE CASCADE,
    job_key          TEXT         NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    company          TEXT,
    job_title        TEXT,
    employees        INTEGER,
    size_band        TEXT,
    confidence       TEXT,
    size_basis       TEXT,
    target           TEXT         NOT NULL,
    target_role      TEXT,
    target_why       TEXT,
    channel          TEXT,
    subject          TEXT,
    connection_note  TEXT,
    message          TEXT,
    follow_up        TEXT,
    search_url       TEXT,
    model            TEXT,
    usage            JSONB
);

CREATE INDEX IF NOT EXISTS outreach_search_job_idx ON outreach (search_id, job_key, created_at DESC);
CREATE INDEX IF NOT EXISTS outreach_created_at_idx ON outreach (created_at DESC);
