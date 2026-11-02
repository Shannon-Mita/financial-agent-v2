-- Financial Agent V2 — Stage 2 Step 4 schema: strategies, their links to
-- goals/milestones, levers, and steps. 001_init.sql and 002_goals.sql are
-- untouched. Same idiom as both: CREATE TABLE IF NOT EXISTS, CHECKs
-- inline, safe to re-run.
--
-- strategy_levers.dimension is a fact key but has NO foreign key to the
-- facts table — facts are a generic append-only key/value log, not one row
-- per key name, so there is nothing to reference. It is validated
-- app-side against a curated set (app/strategies_store.py), the same way
-- goals.source_fact_key is validated against FACT_BACKED_TARGET_VALUE_KEYS
-- in app/permissions.py rather than a DB constraint.
--
-- strategy_goal_links is many-to-many because both apex goals and
-- milestones live in the single `goals` table (Stage 2 §5) — one link
-- table covers both, no separate "milestone link" table needed.

CREATE TABLE IF NOT EXISTS strategies (
    id                          SERIAL PRIMARY KEY,
    title                       TEXT NOT NULL,
    -- NULL = unknown ("?" in the worksheet), same rule as the two numeric
    -- effect fields below — several seeded entries have "Detail: ?" /
    -- "Status: ?" and that must stay distinct from a deliberate empty
    -- string or a fabricated default (Shannon, 3 Nov 2026: "every unknown
    -- staying unknown").
    detail                      TEXT NULL,
    -- §7's Goals-page grouping ("Strategies grouped by area") needs a real
    -- column — the worksheet's own section headings (Shannon, 1 Nov 2026),
    -- stored verbatim so the seed script needs no translation layer.
    area                        TEXT NOT NULL CHECK (area IN
                                 ('Work and income', 'Relocation', 'Business',
                                  'Investing', 'Property', 'Spending')),
    status                      TEXT NULL CHECK (status IS NULL OR status IN
                                 ('idea', 'in progress', 'active', 'parked', 'archived')),
    work_lives_in               TEXT NOT NULL DEFAULT '',
    -- £ by 5 Oct 2030 / £ per month after tax by 5 Oct 2030. NULL = unknown,
    -- shown as "?", never defaulted to zero. A genuine, known zero effect
    -- is stored as the number 0, not NULL (Shannon, 1 Nov 2026).
    effect_on_net_worth         NUMERIC NULL,
    effect_on_passive_income    NUMERIC NULL,
    risks_childcare_eligibility TEXT NOT NULL DEFAULT 'unknown' CHECK (risks_childcare_eligibility IN
                                 ('yes', 'no', 'unknown')),
    from_when                   TEXT NULL,
    archived_reason             TEXT NULL,
    archived_date               DATE NULL,
    last_reviewed_date          DATE NULL,
    source                      TEXT NOT NULL CHECK (source IN ('shannon', 'asha')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id          INTEGER NOT NULL REFERENCES users(id),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by_user_id          INTEGER NOT NULL REFERENCES users(id),
    -- Archive (Shannon, 1 Nov 2026): a required reason and date, not a bare
    -- status flip — enforced structurally, not just by the route.
    CHECK (status != 'archived' OR (archived_reason IS NOT NULL AND archived_date IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS strategy_goal_links (
    strategy_id INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    goal_id     INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    PRIMARY KEY (strategy_id, goal_id)
);

CREATE TABLE IF NOT EXISTS strategy_levers (
    id          SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    dimension   TEXT NOT NULL,
    delta       NUMERIC NOT NULL,
    from_date   DATE NOT NULL
);

-- Mirrors `tasks` structurally (same columns), but strategy_id instead of
-- goal_id, and different permissions: either person may add/edit a step,
-- only the assignee may tick it (app/permissions.py), unlike tasks where
-- add/edit is creator+assignee gated.
CREATE TABLE IF NOT EXISTS strategy_steps (
    id                 SERIAL PRIMARY KEY,
    strategy_id        INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    assignee_user_id   INTEGER NULL REFERENCES users(id),
    done               BOOLEAN NOT NULL DEFAULT false,
    done_at            TIMESTAMPTZ NULL,
    done_by_user_id    INTEGER NULL REFERENCES users(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id)
);
