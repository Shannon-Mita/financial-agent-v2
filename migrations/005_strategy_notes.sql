-- Financial Agent V2 — Stage 2 Step 5 schema: append-only notes on
-- strategies and strategy steps, plus an optional strategy link on
-- decision_log entries. 001-004 are untouched except for the one widening
-- ALTER on audit_log (same idiom as 004) and the one ADD COLUMN on
-- decision_log, both guarded for a safe re-run.
--
-- RESTRICT, not CASCADE/SET NULL, on every FK into strategy_notes and out
-- of decision_log.strategy_id: both tables are append-only via a blocking
-- trigger (see below), and CASCADE/SET NULL would issue a real DELETE/
-- UPDATE under the hood that the SAME trigger would then reject — RESTRICT
-- instead gives a clean FK-violation Postgres can raise directly, which
-- app/routes.py pre-checks and turns into "archive it instead" before ever
-- reaching the DB (Shannon, 16 Nov 2026).

CREATE TABLE IF NOT EXISTS strategy_notes (
    id                 BIGSERIAL PRIMARY KEY,
    strategy_id        INTEGER NOT NULL REFERENCES strategies(id) ON DELETE RESTRICT,
    -- Optional: a note either sits on the strategy generally (NULL) or is
    -- pinned to one specific step of it — app-side checks the step
    -- actually belongs to strategy_id (no DB-level cross-column check for
    -- that; same "validated app-side" precedent as strategy_levers.dimension).
    step_id            INTEGER NULL REFERENCES strategy_steps(id) ON DELETE RESTRICT,
    body               TEXT NOT NULL CHECK (char_length(body) <= 10000),
    -- NULL = no link. When present: https:// only and under 2048 chars —
    -- a coarse backstop only; the app does the real well-formed-URL check
    -- (scheme + a real host) before this is ever reached.
    link               TEXT NULL CHECK (link IS NULL OR
                        (link LIKE 'https://%' AND char_length(link) <= 2048)),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id)
);

CREATE OR REPLACE FUNCTION strategy_notes_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'strategy_notes table is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS strategy_notes_no_update ON strategy_notes;
CREATE TRIGGER strategy_notes_no_update
    BEFORE UPDATE ON strategy_notes
    FOR EACH ROW EXECUTE FUNCTION strategy_notes_block_mutation();

DROP TRIGGER IF EXISTS strategy_notes_no_delete ON strategy_notes;
CREATE TRIGGER strategy_notes_no_delete
    BEFORE DELETE ON strategy_notes
    FOR EACH ROW EXECUTE FUNCTION strategy_notes_block_mutation();

-- Decision log: an optional link to the strategy a decision was about, so
-- it can be shown on that strategy's own page. RESTRICT (see header) — once
-- any decision links to a strategy, that strategy can no longer be
-- deleted (decision_log is append-only, so the link can't be removed
-- either) — archive it instead.
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS strategy_id INTEGER NULL
    REFERENCES strategies(id) ON DELETE RESTRICT;

-- Widen the shared audit_log (002_goals.sql, widened again in 004) to also
-- accept 'strategy_note' — same DROP + re-ADD idiom as 004, so re-running
-- this migration replaces the same constraint rather than stacking a
-- second, narrower one.
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_entity_type_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_entity_type_check
    CHECK (entity_type IN ('goal', 'task', 'decision_log', 'strategy_note'));
