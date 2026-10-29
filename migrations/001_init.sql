-- Financial Agent V2 — Stage 0 schema.
-- Facts are append-only by design (wealth-core's own rule, enforced here at
-- the database level too, not just in application code).

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    google_sub  TEXT NOT NULL UNIQUE,
    email       TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS facts (
    id                  BIGSERIAL PRIMARY KEY,
    key                 TEXT NOT NULL,
    value_text          TEXT NOT NULL,
    value_type          TEXT NOT NULL,
    unit                TEXT NOT NULL,
    source              TEXT NOT NULL,
    category            TEXT NOT NULL,
    owner               TEXT NOT NULL CHECK (owner IN ('shannon', 'partner', 'joint')),
    as_of               DATE NOT NULL,
    entered_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    note                TEXT NOT NULL DEFAULT '',
    entered_by_user_id  INTEGER NOT NULL REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_facts_key_entered ON facts (key, entered_at);

-- Append-only enforcement: no UPDATE or DELETE on facts, ever, even via a bug
-- or a direct psql session. Mirrors wealth-core's own append-only rule, which
-- this database inherits but does not import code from.
CREATE OR REPLACE FUNCTION facts_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'facts table is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS facts_no_update ON facts;
CREATE TRIGGER facts_no_update
    BEFORE UPDATE ON facts
    FOR EACH ROW EXECUTE FUNCTION facts_block_mutation();

DROP TRIGGER IF EXISTS facts_no_delete ON facts;
CREATE TRIGGER facts_no_delete
    BEFORE DELETE ON facts
    FOR EACH ROW EXECUTE FUNCTION facts_block_mutation();
