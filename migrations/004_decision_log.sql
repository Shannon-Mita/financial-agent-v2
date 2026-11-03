-- Financial Agent V2 — decision log: Shannon and Asha each append dated
-- entries (decision/reason/assumptions); nobody edits or deletes, ever.
-- 001_init.sql, 002_goals.sql and 003_strategies.sql are untouched except
-- for the one widening ALTER below. Same idiom as the others: CREATE TABLE
-- IF NOT EXISTS, CHECKs inline, DROP TRIGGER IF EXISTS / CREATE TRIGGER —
-- safe to re-run.
--
-- decision_log is append-only the same way facts/audit_log are: its own
-- trigger blocks UPDATE and DELETE outright, independent of whether the
-- app ever tries one. created_by_user_id has no "updated_by" counterpart
-- — there is nothing to update.

CREATE TABLE IF NOT EXISTS decision_log (
    id                 BIGSERIAL PRIMARY KEY,
    decision_date      DATE NOT NULL,
    decision           TEXT NOT NULL,
    reason             TEXT NOT NULL,
    assumptions        TEXT NOT NULL DEFAULT '',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id)
);

CREATE OR REPLACE FUNCTION decision_log_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'decision_log table is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS decision_log_no_update ON decision_log;
CREATE TRIGGER decision_log_no_update
    BEFORE UPDATE ON decision_log
    FOR EACH ROW EXECUTE FUNCTION decision_log_block_mutation();

DROP TRIGGER IF EXISTS decision_log_no_delete ON decision_log;
CREATE TRIGGER decision_log_no_delete
    BEFORE DELETE ON decision_log
    FOR EACH ROW EXECUTE FUNCTION decision_log_block_mutation();

-- Widen the shared audit_log (002_goals.sql) to also accept a 'decision_log'
-- entity_type, so every decision_log creation can write a row there too —
-- "audit-logged like goals" means this one shared table covers decisions
-- the same way it covers goal/task history, rather than inventing a second
-- audit mechanism. 'audit_log_entity_type_check' is the name Postgres gave
-- the inline CHECK in 002_goals.sql when it was declared with no explicit
-- name (confirmed against a fresh 001+002+003 apply) — DROP + re-ADD under
-- that exact name is what makes this idempotent, not just additive: running
-- it twice replaces the same constraint rather than stacking a second,
-- narrower one that would silently re-block 'decision_log' inserts.
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_entity_type_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_entity_type_check
    CHECK (entity_type IN ('goal', 'task', 'decision_log'));
