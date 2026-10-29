"""
Tests for scripts/restore_data.py, including a full export -> wipe ->
restore -> compare round trip. Needs a real Postgres (skips without
TEST_DATABASE_URL).
"""
import os

import pytest

import app.goals_store as goals_store
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path
from scripts.export_data import TABLES, export_all
from scripts.restore_data import NotEmptyError, refuse_unless_empty, restore_all

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402


def wipe(conn):
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE facts, users, goals, goal_assignees, tasks, audit_log "
            "RESTART IDENTITY CASCADE"
        )
    conn.commit()


def test_refuse_unless_empty_raises_when_any_table_has_rows(pg_conn, owner_user_id):
    with pytest.raises(NotEmptyError, match="users has rows"):
        refuse_unless_empty(pg_conn)


def test_refuse_unless_empty_passes_on_a_genuinely_empty_database(pg_conn):
    refuse_unless_empty(pg_conn)  # no exception


def test_restore_all_refuses_and_writes_nothing_when_not_empty(pg_conn, owner_user_id):
    data = {t: [] for t in TABLES}
    with pytest.raises(NotEmptyError):
        restore_all(pg_conn, data)
    # the one seeded user is still the only row — nothing else got inserted
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users")
        assert cur.fetchone()[0] == 1


def _seed_realistic_data(conn, owner_id, member_id):
    store = PostgresFactStore(conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_id,
    )
    store.set(
        Fact.create("savings.house_deposit.balance", 22000, Unit.GBP, Source.USER_STATED, "balance"),
        owner="joint", entered_by_user_id=owner_id,
    )
    goal_id = goals_store.create_goal(
        conn, title="House deposit", type="target", target_value=70000, target_date="2027-06-30",
        source_fact_key=None, target_date_fact_key=None,
        progress_fact_keys=["savings.house_deposit.balance"], cadence_period=None, cadence_amount=None,
        parent_id=None, assignee_user_ids=[member_id], user_id=owner_id,
    )
    goals_store.create_task(
        conn, title="Open a LISA", goal_id=goal_id, assignee_user_id=member_id, user_id=owner_id,
    )
    goals_store.set_goal_status(conn, goal_id, "done", owner_id)


def test_restore_round_trip_export_wipe_restore_compare(pg_conn, owner_user_id, member_user_id):
    _seed_realistic_data(pg_conn, owner_user_id, member_user_id)

    before = export_all(pg_conn)
    assert sum(len(rows) for rows in before.values()) > 0  # sanity: actually seeded something

    # Round-trip through JSON exactly like the real export file would —
    # catches anything that doesn't survive serialisation (e.g. a type
    # restore_all can't adapt back), not just an in-memory dict copy.
    import json
    serialised = json.loads(json.dumps(before, default=str))

    wipe(pg_conn)
    for table in TABLES:
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0

    restore_all(pg_conn, serialised)

    after = export_all(pg_conn)
    assert after == before


def test_restore_resets_sequences_so_new_rows_dont_collide(pg_conn, owner_user_id, member_user_id):
    _seed_realistic_data(pg_conn, owner_user_id, member_user_id)
    before = export_all(pg_conn)
    max_goal_id = max(g["id"] for g in before["goals"])

    import json
    serialised = json.loads(json.dumps(before, default=str))
    wipe(pg_conn)
    restore_all(pg_conn, serialised)

    new_goal_id = goals_store.create_goal(
        pg_conn, title="New goal after restore", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    assert new_goal_id > max_goal_id


def test_restore_data_main_writes_rows_end_to_end(pg_conn, owner_user_id, monkeypatch, capsys):
    goals_store.create_goal(
        pg_conn, title="Goal", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    before = export_all(pg_conn)

    import json
    export_path = os.path.join(os.path.dirname(__file__), "_tmp_restore_test_export.json")
    with open(export_path, "w") as f:
        json.dump(before, f, default=str)

    wipe(pg_conn)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr("sys.argv", ["restore_data.py", export_path])

    try:
        import scripts.restore_data as restore_data_module
        import importlib
        importlib.reload(restore_data_module)
        restore_data_module.main()

        captured = capsys.readouterr()
        assert "Restored goals: 1 rows" in captured.out
        assert os.environ["TEST_DATABASE_URL"] not in captured.out

        with pg_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM goals")
            assert cur.fetchone()[0] == 1
    finally:
        os.remove(export_path)


def test_main_requires_an_export_file_argument(monkeypatch):
    import importlib

    import scripts.restore_data as restore_data_module

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    monkeypatch.setattr("sys.argv", ["restore_data.py"])
    importlib.reload(restore_data_module)
    with pytest.raises(SystemExit):
        restore_data_module.main()


def test_main_requires_database_url(monkeypatch):
    import importlib

    import scripts.restore_data as restore_data_module

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["restore_data.py", "whatever.json"])
    importlib.reload(restore_data_module)
    with pytest.raises(SystemExit):
        restore_data_module.main()
