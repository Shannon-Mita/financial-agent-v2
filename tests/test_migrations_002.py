"""
Schema-level tests for migrations/002_goals.sql — the goals/tasks/audit_log
tables, their CHECK constraints, and audit_log's append-only enforcement.
Needs a real Postgres (skips without TEST_DATABASE_URL), same as
test_append_only.py and test_store_contract.py.
"""
import psycopg2
import pytest


def _insert_goal(cur, **overrides):
    row = dict(
        title="FIRE",
        type="target",
        target_value=None,
        target_date=None,
        source_fact_key="goals.fire.target_number",
        target_date_fact_key="goals.fire.target_date",
        created_by_user_id=overrides.pop("user_id"),
    )
    row.update(overrides)
    row["updated_by_user_id"] = row["created_by_user_id"]
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO goals ({cols}) VALUES ({placeholders}) RETURNING id",
        list(row.values()),
    )
    return cur.fetchone()[0]


def test_goals_table_has_no_owner_column(pg_conn):
    """Shannon's answer 3: the goals table carries no owner column — who may
    write a goal is role-only. Pins this so a future migration can't
    reintroduce it unnoticed."""
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'goals'"
        )
        columns = {r[0] for r in cur.fetchall()}
    assert "owner" not in columns


def test_goal_check_rejects_dual_stored_and_fact_backed_target_value(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_goal(
                cur, user_id=owner_user_id,
                target_value=70000, source_fact_key="goals.fire.target_number",
            )
    pg_conn.rollback()


def test_goal_check_rejects_dual_stored_and_fact_backed_target_date(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_goal(
                cur, user_id=owner_user_id,
                target_date="2030-10-05", target_date_fact_key="goals.fire.target_date",
            )
    pg_conn.rollback()


def test_fact_backed_goal_row_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        goal_id = _insert_goal(cur, user_id=owner_user_id)
    pg_conn.commit()
    assert goal_id is not None


def test_locally_stored_goal_row_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        goal_id = _insert_goal(
            cur, user_id=owner_user_id,
            title="House deposit", type="target",
            target_value=70000, target_date="2027-06-30",
            source_fact_key=None, target_date_fact_key=None,
        )
    pg_conn.commit()
    assert goal_id is not None


def test_goal_type_check_rejects_unknown_type(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_goal(cur, user_id=owner_user_id, type="not-a-real-type")
    pg_conn.rollback()


def test_goals_table_allows_update_unlike_facts(pg_conn, owner_user_id):
    """goals (unlike facts/audit_log) is a mutable table — status changes
    are expected, not blocked."""
    with pg_conn.cursor() as cur:
        goal_id = _insert_goal(cur, user_id=owner_user_id)
        cur.execute("UPDATE goals SET status = 'done' WHERE id = %s", (goal_id,))
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT status FROM goals WHERE id = %s", (goal_id,))
        assert cur.fetchone()[0] == "done"


def test_audit_log_blocks_update(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id)
            VALUES ('goal', 1, 'created', '{}', %s) RETURNING id
            """,
            (owner_user_id,),
        )
        log_id = cur.fetchone()[0]
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute("UPDATE audit_log SET event_type = 'deleted' WHERE id = %s", (log_id,))
    pg_conn.rollback()


def test_audit_log_blocks_delete(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id)
            VALUES ('task', 1, 'created', '{}', %s) RETURNING id
            """,
            (owner_user_id,),
        )
        log_id = cur.fetchone()[0]
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute("DELETE FROM audit_log WHERE id = %s", (log_id,))
    pg_conn.rollback()


def test_task_created_and_toggled(pg_conn, owner_user_id, member_user_id):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (title, assignee_user_id, created_by_user_id)
            VALUES ('Open an ISA', %s, %s) RETURNING id
            """,
            (member_user_id, owner_user_id),
        )
        task_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE tasks SET done = true, done_by_user_id = %s WHERE id = %s",
            (member_user_id, task_id),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT done FROM tasks WHERE id = %s", (task_id,))
        assert cur.fetchone()[0] is True
