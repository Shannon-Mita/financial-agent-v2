"""
UI-only fix: the Goals page rendered every top-level goal as an equal peer
in a grid, so FIRE (the one real apex goal, with milestones beneath it)
read as just another card next to its own children. No data model change,
no new fields — this only changes how goals_list.html lays out what
routes.goals_list() already computes (it already identified `fire_goal`
for the FIRE-breakdown card; it just never passed that identification
through to the hierarchy rendering).
"""
import re

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


def test_fire_renders_as_apex_with_milestones_heading(client, pg_conn, owner_user_id, member_user_id):
    fire_id, deposit_id, emergency_id = _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    assert "Milestones" in body
    # FIRE's own card appears before the Milestones heading...
    fire_pos = body.find(">FIRE<")
    milestones_pos = body.find("Milestones")
    assert 0 <= fire_pos < milestones_pos
    # ...and both milestones appear after it, nested.
    deposit_pos = body.find(">House deposit<")
    emergency_pos = body.find(">Emergency fund<")
    assert milestones_pos < deposit_pos
    assert milestones_pos < emergency_pos


def test_milestones_are_visually_nested_not_flat_peers(client, pg_conn, owner_user_id, member_user_id):
    fire_id, deposit_id, emergency_id = _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    # The milestone cards carry the existing nested/indented card styling —
    # same mechanism goal_detail.html already uses for sub-goals.
    deposit_card_start = body.rfind("<div class=\"card sub\">", 0, body.find(">House deposit<"))
    assert deposit_card_start != -1
    emergency_card_start = body.rfind("<div class=\"card sub\">", 0, body.find(">Emergency fund<"))
    assert emergency_card_start != -1


def test_fire_is_not_duplicated_in_the_flat_grid(client, pg_conn, owner_user_id, member_user_id):
    """FIRE must appear exactly once — as the apex — not also show up a
    second time amongst any other top-level goals."""
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert body.count(">FIRE</a>") == 1  # the goal card's own title link, not the apex <h2> heading


def test_other_top_level_goals_still_render_without_milestones_label(client, pg_conn, owner_user_id, member_user_id):
    """A goal that isn't FIRE (no source_fact_key pointing at the FIRE
    target) and has no parent is still a legitimate top-level goal — it
    must still show up, just not mislabelled as FIRE's milestones."""
    fire_id, _, _ = _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    other_id = goals_store.create_goal(
        pg_conn, title="Learn Spanish", type="habit", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period="weekly", cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "Learn Spanish" in body
    # It renders after the apex/milestones section, as its own top-level card.
    assert body.find("Milestones") < body.find("Learn Spanish")


def test_no_fire_goal_falls_back_to_plain_flat_list(client, pg_conn, owner_user_id):
    """No FIRE goal at all (e.g. a fresh household) — no apex section, no
    "Milestones" heading, just the existing flat rendering. Must not error."""
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


def test_member_also_sees_fire_as_apex(client, pg_conn, owner_user_id, member_user_id):
    _make_fire_with_milestones(pg_conn, owner_user_id, member_user_id)
    login(client, member_user_id)
    body = client.get("/goals").data.decode()
    assert "Milestones" in body
    assert body.find(">FIRE<") < body.find("Milestones") < body.find(">House deposit<")
