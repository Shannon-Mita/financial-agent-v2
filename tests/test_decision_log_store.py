"""
Tests for app/decision_log_store.py — list/create for the decision log, and
that creating a decision also writes a shared audit_log row (same pattern
as app/goals_store.py's create_goal). Needs a real Postgres (skips without
TEST_DATABASE_URL).
"""
import app.decision_log_store as decision_log_store


def test_create_decision_returns_an_id(pg_conn, owner_user_id):
    decision_id = decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="Switch mortgage lender",
        reason="New rate is 1.2% lower", assumptions="Rate holds until completion",
        user_id=owner_user_id,
    )
    assert decision_id is not None


def test_create_decision_defaults_blank_assumptions_to_empty_string(pg_conn, owner_user_id):
    decision_id = decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="Decision", reason="Reason",
        assumptions="", user_id=owner_user_id,
    )
    decisions = decision_log_store.list_decisions(pg_conn)
    assert [d for d in decisions if d["id"] == decision_id][0]["assumptions"] == ""


def test_create_decision_writes_an_audit_log_row(pg_conn, owner_user_id):
    decision_id = decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="Decision", reason="Reason",
        assumptions="", user_id=owner_user_id,
    )
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT entity_type, entity_id, event_type, changed_by_user_id FROM audit_log WHERE entity_id = %s",
            (decision_id,),
        )
        row = cur.fetchone()
    assert row == ("decision_log", decision_id, "created", owner_user_id)


def test_list_decisions_is_newest_first_by_decision_date(pg_conn, owner_user_id):
    older = decision_log_store.create_decision(
        pg_conn, decision_date="2026-01-01", decision="Older", reason="r", assumptions="",
        user_id=owner_user_id,
    )
    newer = decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="Newer", reason="r", assumptions="",
        user_id=owner_user_id,
    )
    decisions = decision_log_store.list_decisions(pg_conn)
    ids_in_order = [d["id"] for d in decisions]
    assert ids_in_order.index(newer) < ids_in_order.index(older)


def test_list_decisions_breaks_ties_on_same_date_by_newest_created(pg_conn, owner_user_id):
    first = decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="First", reason="r", assumptions="",
        user_id=owner_user_id,
    )
    second = decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="Second", reason="r", assumptions="",
        user_id=owner_user_id,
    )
    decisions = decision_log_store.list_decisions(pg_conn)
    ids_in_order = [d["id"] for d in decisions]
    assert ids_in_order.index(second) < ids_in_order.index(first)


def test_list_decisions_includes_both_people(pg_conn, owner_user_id, member_user_id):
    decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-01", decision="Shannon's decision", reason="r",
        assumptions="", user_id=owner_user_id,
    )
    decision_log_store.create_decision(
        pg_conn, decision_date="2026-11-02", decision="Asha's decision", reason="r",
        assumptions="", user_id=member_user_id,
    )
    decisions = decision_log_store.list_decisions(pg_conn)
    assert {d["created_by_user_id"] for d in decisions} == {owner_user_id, member_user_id}
