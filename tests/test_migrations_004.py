"""
Schema-level tests for migrations/004_decision_log.sql — the decision_log
table, its append-only enforcement (mirrors facts/audit_log), and the
widened audit_log.entity_type CHECK that lets a decision_log row also
write a shared audit_log entry. Needs a real Postgres (skips without
TEST_DATABASE_URL), same as test_migrations_002.py/test_migrations_003.py.
"""
import psycopg2
import pytest


def _insert_decision(cur, **overrides):
    row = dict(
        decision_date="2026-11-02",
        decision="Move the emergency fund to a higher-rate account",
        reason="Current account pays 0.1%, the new one pays 4.5%",
        assumptions="Rate stays above 4% for at least a year",
        created_by_user_id=overrides.pop("user_id"),
    )
    row.update(overrides)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO decision_log ({cols}) VALUES ({placeholders}) RETURNING id",
        list(row.values()),
    )
    return cur.fetchone()[0]


def test_decision_with_all_fields_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        decision_id = _insert_decision(cur, user_id=owner_user_id)
    pg_conn.commit()
    assert decision_id is not None


def test_assumptions_defaults_to_empty_string_not_null(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO decision_log (decision_date, decision, reason, created_by_user_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            ("2026-11-02", "Decision", "Reason", owner_user_id),
        )
        decision_id = cur.fetchone()[0]
        cur.execute("SELECT assumptions FROM decision_log WHERE id = %s", (decision_id,))
        value = cur.fetchone()[0]
    pg_conn.commit()
    assert value == ""


def test_missing_decision_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                "INSERT INTO decision_log (decision_date, reason, created_by_user_id) "
                "VALUES (%s, %s, %s)",
                ("2026-11-02", "Reason", owner_user_id),
            )
    pg_conn.rollback()


def test_missing_reason_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                "INSERT INTO decision_log (decision_date, decision, created_by_user_id) "
                "VALUES (%s, %s, %s)",
                ("2026-11-02", "Decision", owner_user_id),
            )
    pg_conn.rollback()


def test_missing_decision_date_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                "INSERT INTO decision_log (decision, reason, created_by_user_id) "
                "VALUES (%s, %s, %s)",
                ("Decision", "Reason", owner_user_id),
            )
    pg_conn.rollback()


# ── Append-only, same pattern as test_append_only.py's facts coverage ────

def test_update_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        decision_id = _insert_decision(cur, user_id=owner_user_id)
    pg_conn.commit()
    with pytest.raises(psycopg2.Error):
        with pg_conn.cursor() as cur:
            cur.execute("UPDATE decision_log SET decision = 'Changed' WHERE id = %s", (decision_id,))
    pg_conn.rollback()


def test_delete_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        decision_id = _insert_decision(cur, user_id=owner_user_id)
    pg_conn.commit()
    with pytest.raises(psycopg2.Error):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM decision_log WHERE id = %s", (decision_id,))
    pg_conn.rollback()


# ── audit_log.entity_type widened to accept 'decision_log' ──────────────

def test_audit_log_accepts_decision_log_entity_type(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        decision_id = _insert_decision(cur, user_id=owner_user_id)
        cur.execute(
            "INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id) "
            "VALUES ('decision_log', %s, 'created', '{}'::jsonb, %s)",
            (decision_id, owner_user_id),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT entity_type FROM audit_log WHERE entity_id = %s", (decision_id,))
        assert cur.fetchone()[0] == "decision_log"


def test_audit_log_still_rejects_an_unknown_entity_type(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id) "
                "VALUES ('not_a_real_entity', 1, 'created', '{}'::jsonb, %s)",
                (owner_user_id,),
            )
    pg_conn.rollback()


def test_audit_log_still_rejects_goal_and_task_mutation(pg_conn):
    """Pins that re-running the migration's ALTER (DROP + ADD CONSTRAINT)
    doesn't silently lose the original goal/task values from the CHECK."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
                    ("audit_log_entity_type_check",))
        row = cur.fetchone()
    assert row is not None
    definition = row[1]
    assert "goal" in definition
    assert "task" in definition
    assert "decision_log" in definition


def test_migration_004_is_idempotent(pg_conn):
    """Re-applying 004 (same as apply_migrations.py re-running the whole
    set) must not error and must not duplicate the widened constraint."""
    import os

    from app.db import run_migration

    path = os.path.join(os.path.dirname(__file__), "..", "migrations", "004_decision_log.sql")
    run_migration(pg_conn, path)
    run_migration(pg_conn, path)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_constraint WHERE conname = %s", ("audit_log_entity_type_check",))
        assert cur.fetchone()[0] == 1
