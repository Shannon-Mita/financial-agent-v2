"""
Schema-level tests for migrations/005_strategy_notes.sql — the append-only
strategy_notes table, decision_log's new optional strategy_id link, and the
widened audit_log.entity_type CHECK. Needs a real Postgres (skips without
TEST_DATABASE_URL), same as test_migrations_003.py/test_migrations_004.py.

RESTRICT, not CASCADE/SET NULL (Shannon, 16 Nov 2026): strategy_notes and
decision_log are both append-only via a blocking trigger — CASCADE/SET NULL
on a strategy delete would issue a real DELETE/UPDATE against those tables
under the hood, which that same trigger would then reject, aborting the
whole strategy delete with a raw FK/trigger error instead of a clean
app-level message. RESTRICT lets Postgres refuse the delete outright
instead; app/routes.py pre-checks and gives the "archive it instead"
message before ever reaching the DB.
"""
import psycopg2
import pytest


def _insert_strategy(cur, **overrides):
    row = dict(
        title="Test strategy",
        area="Business",
        status="idea",
        source="shannon",
        created_by_user_id=overrides.pop("user_id"),
    )
    row.update(overrides)
    row["updated_by_user_id"] = row["created_by_user_id"]
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO strategies ({cols}) VALUES ({placeholders}) RETURNING id",
        list(row.values()),
    )
    return cur.fetchone()[0]


def _insert_step(cur, strategy_id, user_id, **overrides):
    row = dict(strategy_id=strategy_id, title="Do the thing", created_by_user_id=user_id)
    row.update(overrides)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO strategy_steps ({cols}) VALUES ({placeholders}) RETURNING id",
        list(row.values()),
    )
    return cur.fetchone()[0]


def _insert_note(cur, strategy_id, user_id, **overrides):
    row = dict(strategy_id=strategy_id, body="Looked into this, seems promising.", created_by_user_id=user_id)
    row.update(overrides)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO strategy_notes ({cols}) VALUES ({placeholders}) RETURNING id",
        list(row.values()),
    )
    return cur.fetchone()[0]


# ── Basic shape ───────────────────────────────────────────────────────────

def test_note_with_minimal_fields_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id)
    pg_conn.commit()
    assert note_id is not None


def test_note_can_optionally_be_pinned_to_a_step(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        step_id = _insert_step(cur, strategy_id, owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id, step_id=step_id)
        cur.execute("SELECT step_id FROM strategy_notes WHERE id = %s", (note_id,))
        assert cur.fetchone()[0] == step_id
    pg_conn.commit()


def test_note_with_a_valid_https_link_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id, link="https://example.com/research")
        cur.execute("SELECT link FROM strategy_notes WHERE id = %s", (note_id,))
        assert cur.fetchone()[0] == "https://example.com/research"
    pg_conn.commit()


def test_missing_body_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                "INSERT INTO strategy_notes (strategy_id, created_by_user_id) VALUES (%s, %s)",
                (strategy_id, owner_user_id),
            )
    pg_conn.rollback()


# ── DB-level backstop checks (the app does the real validation; these are
# just the coarse last line of defence) ──────────────────────────────────

def test_a_non_https_link_is_rejected_at_the_db_level(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_note(cur, strategy_id, owner_user_id, link="http://example.com")
    pg_conn.rollback()


def test_an_oversized_link_is_rejected_at_the_db_level(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        too_long = "https://example.com/" + ("a" * 2048)
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_note(cur, strategy_id, owner_user_id, link=too_long)
    pg_conn.rollback()


def test_an_oversized_body_is_rejected_at_the_db_level(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_note(cur, strategy_id, owner_user_id, body="x" * 10001)
    pg_conn.rollback()


def test_a_body_at_exactly_the_cap_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id, body="x" * 10000)
    pg_conn.commit()
    assert note_id is not None


# ── Append-only, same pattern as test_append_only.py / test_migrations_004.py ──

def test_update_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id)
    pg_conn.commit()
    with pytest.raises(psycopg2.Error):
        with pg_conn.cursor() as cur:
            cur.execute("UPDATE strategy_notes SET body = 'Changed' WHERE id = %s", (note_id,))
    pg_conn.rollback()


def test_delete_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id)
    pg_conn.commit()
    with pytest.raises(psycopg2.Error):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM strategy_notes WHERE id = %s", (note_id,))
    pg_conn.rollback()


# ── RESTRICT, not CASCADE/SET NULL — deleting a parent with history fails ──

def test_deleting_a_strategy_with_a_note_is_blocked_by_the_fk(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        _insert_note(cur, strategy_id, owner_user_id)
    pg_conn.commit()
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
    pg_conn.rollback()


def test_deleting_a_step_with_a_note_is_blocked_by_the_fk(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        step_id = _insert_step(cur, strategy_id, owner_user_id)
        _insert_note(cur, strategy_id, owner_user_id, step_id=step_id)
    pg_conn.commit()
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM strategy_steps WHERE id = %s", (step_id,))
    pg_conn.rollback()


def test_a_strategy_or_step_with_no_notes_still_deletes_fine(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        step_id = _insert_step(cur, strategy_id, owner_user_id)
        cur.execute("DELETE FROM strategy_steps WHERE id = %s", (step_id,))
        cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM strategies WHERE id = %s", (strategy_id,))
        assert cur.fetchone()[0] == 0


# ── decision_log.strategy_id ─────────────────────────────────────────────

def test_decision_can_optionally_link_a_strategy(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute(
            "INSERT INTO decision_log (decision_date, decision, reason, strategy_id, created_by_user_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            ("2026-11-16", "Pursue it", "Looks promising", strategy_id, owner_user_id),
        )
        decision_id = cur.fetchone()[0]
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT strategy_id FROM decision_log WHERE id = %s", (decision_id,))
        assert cur.fetchone()[0] == strategy_id


def test_decision_strategy_link_defaults_to_null(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO decision_log (decision_date, decision, reason, created_by_user_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            ("2026-11-16", "Some decision", "Some reason", owner_user_id),
        )
        decision_id = cur.fetchone()[0]
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT strategy_id FROM decision_log WHERE id = %s", (decision_id,))
        assert cur.fetchone()[0] is None


def test_deleting_a_strategy_linked_from_a_decision_is_blocked_by_the_fk(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute(
            "INSERT INTO decision_log (decision_date, decision, reason, strategy_id, created_by_user_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("2026-11-16", "Pursue it", "Looks promising", strategy_id, owner_user_id),
        )
    pg_conn.commit()
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
    pg_conn.rollback()


# ── audit_log.entity_type widened to accept 'strategy_note' ─────────────

def test_audit_log_accepts_strategy_note_entity_type(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        note_id = _insert_note(cur, strategy_id, owner_user_id)
        cur.execute(
            "INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id) "
            "VALUES ('strategy_note', %s, 'created', '{}'::jsonb, %s)",
            (note_id, owner_user_id),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT entity_type FROM audit_log WHERE entity_id = %s", (note_id,))
        assert cur.fetchone()[0] == "strategy_note"


def test_audit_log_still_rejects_an_unknown_entity_type(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id) "
                "VALUES ('not_a_real_entity', 1, 'created', '{}'::jsonb, %s)",
                (owner_user_id,),
            )
    pg_conn.rollback()


def test_audit_log_constraint_still_covers_every_earlier_entity_type(pg_conn):
    """Pins that re-running the migration's ALTER (DROP + ADD CONSTRAINT)
    doesn't silently lose any earlier value from the CHECK."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
                    ("audit_log_entity_type_check",))
        row = cur.fetchone()
    assert row is not None
    definition = row[0]
    for value in ("goal", "task", "decision_log", "strategy_note"):
        assert value in definition


def test_migration_005_is_idempotent(pg_conn):
    """Re-applying 005 must not error and must not duplicate the widened
    constraint."""
    import os

    from app.db import run_migration

    path = os.path.join(os.path.dirname(__file__), "..", "migrations", "005_strategy_notes.sql")
    run_migration(pg_conn, path)
    run_migration(pg_conn, path)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_constraint WHERE conname = %s", ("audit_log_entity_type_check",))
        assert cur.fetchone()[0] == 1
