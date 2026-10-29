"""
Tests for scripts/export_data.py. Needs a real Postgres (skips without
TEST_DATABASE_URL).
"""
import importlib
import json
import os

import app.goals_store as goals_store
from scripts.export_data import TABLES, export_all


def real_schema_tables(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        return {r[0] for r in cur.fetchall()}


def test_export_tables_match_every_table_in_the_real_schema(pg_conn):
    """Ties the export to the actual schema, not a hand-maintained list —
    a future migration adding a table fails this until the export (and this
    test) is updated to include it."""
    assert set(TABLES.keys()) == real_schema_tables(pg_conn)


def test_export_includes_rows_from_every_table(pg_conn, owner_user_id, member_user_id):
    from app.store import PostgresFactStore
    from app.vendor_path import ensure_on_path

    ensure_on_path()
    from facts_layer import Fact, Source, Unit

    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    goal_id = goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-06-30",
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    task_id = goals_store.create_task(
        pg_conn, title="Open a LISA", goal_id=goal_id, assignee_user_id=member_user_id, user_id=owner_user_id,
    )

    data = export_all(pg_conn)

    assert len(data["users"]) == 2
    assert len(data["facts"]) == 1
    assert len(data["goals"]) == 1
    assert data["goals"][0]["id"] == goal_id
    assert len(data["goal_assignees"]) == 1
    assert data["goal_assignees"][0] == {"goal_id": goal_id, "user_id": member_user_id}
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["id"] == task_id
    # create_goal + create_task each write a 'created' audit_log row.
    assert len(data["audit_log"]) == 2
    assert {r["event_type"] for r in data["audit_log"]} == {"created"}


def test_export_writes_a_file_with_correct_row_counts(pg_conn, owner_user_id, monkeypatch, capsys):
    goals_store.create_goal(
        pg_conn, title="Goal", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("EXPORT_TIMESTAMP", "TESTSTAMP-EXPORT")

    import scripts.export_data as export_data_module
    importlib.reload(export_data_module)
    export_data_module.main()

    # main() resolves its own output dir relative to the script's __file__,
    # not the cwd — so the real repo exports/ dir, regardless of where
    # pytest was invoked from.
    out_dir = os.path.join(os.path.dirname(export_data_module.__file__), "..", "exports")
    out_path = os.path.join(out_dir, "financial-agent-v2-export-TESTSTAMP-EXPORT.json")
    try:
        assert os.path.exists(out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert len(data["goals"]) == 1
        assert set(data.keys()) == set(TABLES.keys())

        captured = capsys.readouterr()
        assert "Wrote" in captured.out
        assert "goals: 1 rows" in captured.out
        assert os.environ["TEST_DATABASE_URL"] not in captured.out
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)
