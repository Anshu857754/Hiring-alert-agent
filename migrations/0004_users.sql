-- Multi-user. Ab tak app single-user thi (ek .env, ek banda, ek password gate).
-- Yahan se har banda apna account banata hai, apni API keys deta hai, aur
-- sirf apna data dekhta hai.
--
-- Do nayi tables + har purani table par ek `user_id`.

CREATE TABLE IF NOT EXISTS users (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_login_at      TIMESTAMPTZ,
    email              TEXT         NOT NULL,
    name               TEXT,
    -- scrypt(password, salt) — dono hex me. Koi extra dependency nahi lagti,
    -- hashlib.scrypt stdlib me hai aur memory-hard hai.
    password_hash      TEXT         NOT NULL,
    password_salt      TEXT         NOT NULL,
    -- Har user apni keys laata hai. Fernet se sealed (app/crypto.py) —
    -- server ki .env wali keys kisi aur user ko kabhi nahi milti.
    apify_key_enc      TEXT,
    openrouter_key_enc TEXT
);

-- Email case-insensitive unique. citext extension Neon par har jagah nahi
-- milti, isliye lower() par functional index — sasta aur portable.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_uniq ON users (lower(email));

-- Server-side sessions: logout sach me revoke karta hai. Signed cookie hoti
-- to logout sirf browser se cookie hatata, token zinda rehta.
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT         PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ  NOT NULL,
    user_agent  TEXT
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions (expires_at);

-- ── har data table ko ek maalik ── --
-- Purani rows ka user_id NULL rehta hai. Pehla banda jo signup karega wo
-- inhe adopt kar leta hai (app/users.py -> adopt_orphans), isliye yahan
-- koi backfill guess nahi kar rahe.

ALTER TABLE searches        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE saved_jobs      ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE plans           ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE outreach        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE contacts        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE sender_accounts ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS searches_user_idx        ON searches (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS saved_jobs_user_idx      ON saved_jobs (user_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS outreach_user_idx        ON outreach (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS contacts_user_idx        ON contacts (user_id, discovered_at DESC);
CREATE INDEX IF NOT EXISTS sender_accounts_user_idx ON sender_accounts (user_id);

-- ── unique constraints ab per-user honi chahiye ── --
-- Warna do users ek hi job save nahi kar paate, aur ek hi decision maker
-- dono ki list me nahi aa sakta. Ye seedha bug hota.

ALTER TABLE saved_jobs DROP CONSTRAINT IF EXISTS saved_jobs_job_key_key;
DROP INDEX IF EXISTS saved_jobs_job_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS saved_jobs_user_key_uniq ON saved_jobs (user_id, job_key);

ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_profile_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS contacts_user_profile_uniq ON contacts (user_id, profile_url);

-- Default sender har user ka apna hota hai.
DROP INDEX IF EXISTS sender_accounts_one_default;
CREATE UNIQUE INDEX IF NOT EXISTS sender_accounts_user_default
    ON sender_accounts (user_id) WHERE is_default;
