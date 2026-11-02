"""
Tests for app/strategies_store.py — plain parameterised SQL, no ORM, same
style as app/goals_store.py (but no audit_log: not part of Stage 2 §5's
data model). Needs a real Postgres (skips without TEST_DATABASE_URL).
"""
import app.goals_store as goals_store
import app.strategies_store as strategies_store


def _make_goal(pg_conn, owner_user_id, key="goals.net_worth.target_amount", date_key="goals.net_worth.target_date"):
    return goals_store.create_goal(
        pg_conn, title="Net worth", type="target", target_value=None, target_date=None,
        source_fact_key=key, target_date_fact_key=date_key,
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )


def test_create_and_get_strategy(pg_conn, owner_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="New role", detail="Sales roles for commission.",
        area="Work and income", status="in progress", work_lives_in="Job Hunt project", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None,
        user_id=owner_user_id,
    )
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["title"] == "New role"
    assert s["status"] == "in progress"
    assert s["effect_on_net_worth"] is None
    assert s["effect_on_passive_income"] is None


def test_create_strategy_with_a_genuine_zero_effect(pg_conn, owner_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Mahired / Welfound", detail="Not operating to produce profit.",
        area="Business", status="parked", work_lives_in="Business Ideas project", source="shannon",
        effect_on_net_worth=0, effect_on_passive_income=0,
        risks_childcare_eligibility="unknown", from_when="n/a",
        user_id=owner_user_id,
    )
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["effect_on_net_worth"] == 0
    assert s["effect_on_passive_income"] == 0


def test_list_strategies_excludes_nothing_by_default(pg_conn, owner_user_id):
    strategies_store.create_strategy(
        pg_conn, title="A", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    strategies_store.create_strategy(
        pg_conn, title="B", detail="", area="Business", status="idea", work_lives_in="here", source="asha",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    assert len(strategies_store.list_strategies(pg_conn)) == 2


def test_update_strategy_fields(pg_conn, owner_user_id, member_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    strategies_store.update_strategy(
        pg_conn, strategy_id,
        dict(title="Renamed", detail="New detail", status="active", work_lives_in="here",
             effect_on_net_worth=5000, effect_on_passive_income=100,
             risks_childcare_eligibility="no", from_when="2027-01-01",
             last_reviewed_date="2026-11-03"),
        user_id=member_user_id,
    )
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["title"] == "Renamed"
    assert s["effect_on_net_worth"] == 5000
    assert s["updated_by_user_id"] == member_user_id


def test_archive_strategy_requires_reason_and_date(pg_conn, owner_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    strategies_store.archive_strategy(
        pg_conn, strategy_id, reason="No longer relevant", archived_date="2026-11-03", user_id=owner_user_id,
    )
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["status"] == "archived"
    assert s["archived_reason"] == "No longer relevant"
    assert str(s["archived_date"]) == "2026-11-03"


def test_delete_strategy(pg_conn, owner_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    strategies_store.delete_strategy(pg_conn, strategy_id, user_id=owner_user_id)
    assert strategies_store.get_strategy(pg_conn, strategy_id) is None


def test_set_strategy_goal_links_replaces_wholesale(pg_conn, owner_user_id):
    goal_id = _make_goal(pg_conn, owner_user_id)
    other_goal_id = _make_goal(
        pg_conn, owner_user_id,
        key="goals.passive_income.target_amount", date_key="goals.passive_income.target_date",
    )
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    strategies_store.set_strategy_goal_links(pg_conn, strategy_id, [goal_id])
    assert strategies_store.list_strategy_goal_ids(pg_conn, strategy_id) == [goal_id]

    strategies_store.set_strategy_goal_links(pg_conn, strategy_id, [other_goal_id])
    assert strategies_store.list_strategy_goal_ids(pg_conn, strategy_id) == [other_goal_id]


def test_set_strategy_levers_replaces_wholesale(pg_conn, owner_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    strategies_store.set_strategy_levers(pg_conn, strategy_id, [
        {"dimension": "income.shannon.paye_salary", "delta": 10000, "from_date": "2027-01-01"},
    ])
    levers = strategies_store.list_strategy_levers(pg_conn, strategy_id)
    assert len(levers) == 1
    assert levers[0]["dimension"] == "income.shannon.paye_salary"

    strategies_store.set_strategy_levers(pg_conn, strategy_id, [])
    assert strategies_store.list_strategy_levers(pg_conn, strategy_id) == []


def test_create_list_get_strategy_step(pg_conn, owner_user_id, member_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Open an account",
        assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    step = strategies_store.get_strategy_step(pg_conn, step_id)
    assert step["title"] == "Open an account"
    assert step["done"] is False
    steps = strategies_store.list_strategy_steps(pg_conn, strategy_id)
    assert len(steps) == 1


def test_update_strategy_step(pg_conn, owner_user_id, member_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Orig title",
        assignee_user_id=None, user_id=owner_user_id,
    )
    strategies_store.update_strategy_step(
        pg_conn, step_id, title="New title", assignee_user_id=member_user_id, user_id=member_user_id,
    )
    step = strategies_store.get_strategy_step(pg_conn, step_id)
    assert step["title"] == "New title"
    assert step["assignee_user_id"] == member_user_id


def test_toggle_strategy_step(pg_conn, owner_user_id, member_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Open an account",
        assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    strategies_store.toggle_strategy_step(pg_conn, step_id, True, member_user_id)
    step = strategies_store.get_strategy_step(pg_conn, step_id)
    assert step["done"] is True
    assert step["done_by_user_id"] == member_user_id
    assert step["done_at"] is not None


def test_delete_strategy_step(pg_conn, owner_user_id):
    strategy_id = strategies_store.create_strategy(
        pg_conn, title="Orig", detail="", area="Business", status="idea", work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Open an account",
        assignee_user_id=None, user_id=owner_user_id,
    )
    strategies_store.delete_strategy_step(pg_conn, step_id)
    assert strategies_store.get_strategy_step(pg_conn, step_id) is None
