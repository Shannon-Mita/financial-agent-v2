"""
UI-only fix (28 Oct 2026): the Goals page rendered every top-level goal as
an equal peer in a grid, so a goal with milestones beneath it read as just
another card next to its own children. No data model change, no new
fields — nesting goal_card.html's children under their parent.

UPDATED (Stage 2 Step 3, 2 Nov 2026): FIRE is retired as THE apex goal —
net worth and passive income are the two apexes now (see
tests/test_goals_apex_step3.py). If the old FIRE goal row still exists
(Shannon deletes it himself), it renders as an ordinary top-level goal:
its milestones still nest beneath it (same mechanism every top-level goal
gets), just without the special "Milestones" heading/apex-grid treatment
reserved for the two real apexes now.
"""
import app.goals_store as goals_store
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def _make_fire_with_milestones(pg_conn, owner_id, member_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("goals.fire.target_number", 2_400_000, Unit.GBP, Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=owner_id,
    )
    store.set(
        Fact.create("goals.fire.target_date", "2030-10-05", Unit.DATE, Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=owner_id,
    )
    fire_id = goals_store.create_goal(
        pg_conn, title="FIRE", type="target", target_value=None, target_date=None,
        source_fact_key="goals.fire.target_number", target_date_fact_key="goals.fire.target_date",
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_id, member_id], user_id=owner_id,
    )
    deposit_id = goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-08-29",
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=fire_id,
        assignee_user_ids=[member_id], user_id=owner_id,
    )
    emergency_id = goals_store.create_goal(
        pg_conn, title="Emergency fund", type="target", target_value=15000, target_date="2027-01-01",
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=fire_id,
        assignee_user_ids=[owner_id], user_id=owner_id,
    )
    return fire_id, deposit_id, emergency_id


def test_fire_no_longer_gets_the_apex_milestones_heading(client, pg_conn, owner_user_id, member_user_id):
    """FIRE is retired as an apex (Stage 2 Step 3) — its milestones still
    nest beneath it, just without the "Milestones" heading reserved for
    the two real apexes now."""
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    assert "Milestones" not in body
    assert ">FIRE<" in body
    fire_pos = body.find(">FIRE<")
    deposit_pos = body.find(">House deposit<")
    emergency_pos = body.find(">Emergency fund<")
    assert fire_pos < deposit_pos
    assert fire_pos < emergency_pos


def test_milestones_are_visually_nested_not_flat_peers(client, pg_conn, owner_user_id, member_user_id):
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    # The milestone cards carry the existing nested/indented card styling —
    # same mechanism goal_detail.html already uses for sub-goals.
    deposit_card_start = body.rfind("<div class=\"card sub\">", 0, body.find(">House deposit<"))
    assert deposit_card_start != -1
    emergency_card_start = body.rfind("<div class=\"card sub\">", 0, body.find(">Emergency fund<"))
    assert emergency_card_start != -1


def test_fire_is_not_duplicated_in_the_flat_grid(client, pg_conn, owner_user_id, member_user_id):
    """FIRE must appear exactly once, like any other top-level goal."""
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert body.count(">FIRE</a>") == 1


def test_other_top_level_goals_render_alongside_the_retired_fire_goal(client, pg_conn, owner_user_id, member_user_id):
    """A goal that isn't FIRE and has no parent is still a legitimate
    top-level goal — it shows up as its own card, same as FIRE now does."""
    goals_store.create_goal(
        pg_conn, title="Learn Spanish", type="habit", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period="weekly", cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "Learn Spanish" in body
    assert ">FIRE<" in body


def test_no_fire_goal_falls_back_to_plain_flat_list(client, pg_conn, owner_user_id):
    """No FIRE goal at all (e.g. a fresh household, or after Shannon
    deletes it) — no "Milestones" heading, just the existing flat
    rendering. Must not error."""
    goals_store.create_goal(
        pg_conn, title="Learn Spanish", type="habit", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period="weekly", cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )
    login(client, owner_user_id)
    resp = client.get("/goals")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Milestones" not in body
    assert "Learn Spanish" in body


def test_member_also_sees_the_retired_fire_goal_and_its_nested_milestones(client, pg_conn, owner_user_id, member_user_id):
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, member_user_id)
    body = client.get("/goals").data.decode()
    assert ">FIRE<" in body
    assert body.find(">FIRE<") < body.find(">House deposit<")
