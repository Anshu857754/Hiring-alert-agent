-- Forgot password. Ab tak reset ka koi raasta hi nahi tha — password scrypt se
-- hashed hai, isliye bhoolne par admin ko manually DB me ghusna padta tha.
--
-- Token DB me **plain nahi** rakha jaata: sirf uska sha256 store hota hai.
-- Wajah wahi jo password ke saath hai — DB dump leak ho jaaye to bhi koi
-- link banake kisi ka account nahi khol sakta. Email me raw token jaata hai,
-- verify karte waqt hum usi ka hash nikaal ke match karte hain.

CREATE TABLE IF NOT EXISTS password_resets (
    token_hash  TEXT         PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ  NOT NULL,
    -- Ek token ek hi baar chalta hai. NULL = abhi tak use nahi hua.
    used_at     TIMESTAMPTZ,
    requested_ip TEXT
);

-- "Is user ke purane tokens hatao" har naye request par chalta hai.
CREATE INDEX IF NOT EXISTS password_resets_user_idx   ON password_resets (user_id);
-- Startup par expired rows ki safai.
CREATE INDEX IF NOT EXISTS password_resets_expiry_idx ON password_resets (expires_at);
