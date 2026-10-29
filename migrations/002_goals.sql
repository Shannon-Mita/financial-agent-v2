-- Financial Agent V2 — Stage 1 schema: goals, assignees, tasks, audit log.
-- 001_init.sql is untouched. This file follows its exact idiom so it's safe
-- to re-run: CREATE TABLE IF NOT EXISTS, CHECKs inline (a no-op CREATE never
-- re-attempts them), CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS /
-- CREATE TRIGGER for the append-only enforcement. Runs as one transaction —
-- apply_migrations.py commits once after the whole file, same as 001.
--
-- The FIRE target lives in the facts store (goals.fire.target_number,
-- goals.fire.target_date — both owner-only via the existing "goals." key
-- prefix in app/permissions.py). This table never duplicates that value: a
-- goal is either fact-backed (source_fact_key/target_date_fact_key set, local
-- target_value/target_date left NULL) or locally-stored, never both — the
-- CHECK constraints below make a second stored FIRE number structurally
-- impossible, not just discouraged.
--
-- No `owner` column on `goals` (Shannon's answer 3 on the Stage 1 plan): who
-- may write a goal is governed entirely by role (owner-only), so a
-- per-row `owner` tag would be informational at best and misleading at
-- worst — there is no case where it changes who can edit the row.

CREATE TABLE IF NOT EXISTS goals (
    id                   SERIAL PRIMARY KEY,
    title                TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK (type IN ('target', 'binary', 'habit')),
    target_value         NUMERIC NULL,          -- target type, stored ONLY if not fact-backed
    target_date          DATE NULL,             -- target type, stored ONLY if not fact-backed
    source_fact_key      TEXT NULL,             -- e.g. 'goals.fire.target_number'
    target_date_fact_key TEXT NULL,             -- e.g. 'goals.fire.target_date'
    progress_fact_keys   TEXT[] NULL,           -- facts summed to derive current progress
    cadence_period       TEXT NULL CHECK (cadence_period IN ('weekly', 'monthly')),
    cadence_amount       NUMERIC NULL,          -- habit type, optional
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done', 'abandoned')),
    parent_id            INTEGER NULL REFERENCES goals(id) ON DELETE RESTRICT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id   INTEGER NOT NULL REFERENCES users(id),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by_user_id   INTEGER NOT NULL REFERENCES users(id),
    CHECK (target_value IS NULL OR source_fact_key IS NULL),
    CHECK (target_date IS NULL OR target_date_fact_key IS NULL)
);

CREATE TABLE IF NOT EXISTS goal_assignees (
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (goal_id, user_id)
);

-- `assignee_user_id` is single-valued (unlike goal_assignees) — the build
-- spec's "lightweight checklist item" only ever needs one person on it.
CREATE TABLE IF NOT EXISTS tasks (
    id                 SERIAL PRIMARY KEY,
    goal_id            INTEGER NULL REFERENCES goals(id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    assignee_user_id   INTEGER NULL REFERENCES users(id),
    done               BOOLEAN NOT NULL DEFAULT false,
    done_at            TIMESTAMPTZ NULL,
    done_by_user_id    INTEGER NULL REFERENCES users(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id)
);

-- Shared append-only audit trail for goals/tasks, mirroring 001's
-- facts_block_mutation() trigger pattern but as its own function so 001
-- stays untouched. entity_id has NO foreign key to goals/tasks, deliberately
-- — a hard-deleted goal's history must survive the delete.
CREATE TABLE IF NOT EXISTS audit_log (
    id                 BIGSERIAL PRIMARY KEY,
    entity_type        TEXT NOT NULL CHECK (entity_type IN ('goal', 'task')),
    entity_id          INTEGER NOT NULL,
    event_type         TEXT NOT NULL CHECK (event_type IN
                        ('created', 'updated', 'status_changed', 'assigned', 'unassigned',
                         'task_done', 'task_undone', 'deleted')),
    snapshot           JSONB NOT NULL,
    changed_by_user_id INTEGER NOT NULL REFERENCES users(id),
    changed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION audit_log_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log table is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();
