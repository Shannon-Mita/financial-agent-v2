"""
HTTP-level tests for the Tasks page (GET /tasks) — lists every open task
AND every open strategy step, for both people, grouped by person
(Shannon/Asha/Unassigned), each showing its goal or strategy. Completed
items are hidden. Tick buttons reuse the exact same permission checks as
the existing per-goal/per-strategy pages (can_toggle_task,
can_toggle_strategy_step) — no new permission rule is introduced here.
Needs a real Postgres (skips without TEST_DATABASE_URL).
"""
import re

import app.goals_store as goals_store
import app.strategies_store as strategies_store
from app.vendor_path import ensure_on_path

ensure_on_path()

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m, "expected a csrf_token hidden input on the page"
    return m.group(1)


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def _make_goal(pg_conn, owner_user_id, title="Goal", assignee_user_ids=None):
    return goals_store.create_goal(
        pg_conn, title=title, type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=assignee_user_ids or [], user_id=owner_user_id,
    )


def _make_strategy(pg_conn, owner_user_id, title="Strategy"):
    return strategies_store.create_strategy(
        pg_conn, title=title, detail="", area="Business", status="idea",
        work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )


# ── Access ───────────────────────────────────────────────────────────────

def test_unauthenticated_get_tasks_redirects_to_login(client):
    resp = client.get("/tasks")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_nav_links_to_the_tasks_page(client, owner_user_id):
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert 'href="/tasks"' in body


# ── Grouping, each item showing its goal or strategy ─────────────────────

def test_tasks_grouped_by_person_each_showing_its_goal_or_strategy(
    client, pg_conn, owner_user_id, member_user_id
):
    goal_id = _make_goal(pg_conn, owner_user_id, title="House deposit", assignee_user_ids=[owner_user_id])
    goals_store.create_task(
        pg_conn, title="Owner task", goal_id=goal_id, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    goals_store.create_task(
        pg_conn, title="Member task", goal_id=None, assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    goals_store.create_task(
        pg_conn, title="Orphan task", goal_id=None, assignee_user_id=None, user_id=owner_user_id,
    )

    strategy_id = _make_strategy(pg_conn, owner_user_id, title="Side hustle")
    strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Owner step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Member step", assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Orphan step", assignee_user_id=None, user_id=owner_user_id,
    )

    login(client, owner_user_id)
    body = client.get("/tasks").data.decode()

    shannon_idx = body.index(">Shannon<")
    asha_idx = body.index(">Asha<")
    unassigned_idx = body.index(">Unassigned<")
    assert shannon_idx < asha_idx < unassigned_idx

    for title in ("Owner task", "Owner step"):
        idx = body.index(title)
        assert shannon_idx < idx < asha_idx, f"{title!r} not under Shannon"

    for title in ("Member task", "Member step"):
        idx = body.index(title)
        assert asha_idx < idx < unassigned_idx, f"{title!r} not under Asha"

    for title in ("Orphan task", "Orphan step"):
        assert body.index(title) > unassigned_idx, f"{title!r} not under Unassigned"

    # Each item shows its goal/strategy.
    assert "House deposit" in body
    assert "Side hustle" in body


def test_tasks_page_hides_completed_items(client, pg_conn, owner_user_id):
    open_task_id = goals_store.create_task(
        pg_conn, title="Open task", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    done_task_id = goals_store.create_task(
        pg_conn, title="Done task", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    goals_store.toggle_task(pg_conn, done_task_id, True, owner_user_id)

    strategy_id = _make_strategy(pg_conn, owner_user_id)
    open_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Open step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    done_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Done step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    strategies_store.toggle_strategy_step(pg_conn, done_step_id, True, owner_user_id)

    login(client, owner_user_id)
    body = client.get("/tasks").data.decode()

    assert "Open task" in body
    assert "Open step" in body
    assert "Done task" not in body
    assert "Done step" not in body
    assert open_task_id and done_task_id and open_step_id  # ids used only for setup


def test_member_sees_every_open_item_even_items_she_cant_tick(client, pg_conn, owner_user_id, member_user_id):
    goals_store.create_task(
        pg_conn, title="Owner-only visible", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    body = client.get("/tasks").data.decode()
    assert "Owner-only visible" in body


# ── Permission tests for Asha (member): tick buttons only on her own ────

def test_member_tick_buttons_only_on_her_own_task_and_step(client, pg_conn, owner_user_id, member_user_id):
    owner_task_id = goals_store.create_task(
        pg_conn, title="Owner task", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    her_task_id = goals_store.create_task(
        pg_conn, title="Her task", goal_id=None, assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    unassigned_task_id = goals_store.create_task(
        pg_conn, title="Unassigned task", goal_id=None, assignee_user_id=None, user_id=owner_user_id,
    )

    strategy_id = _make_strategy(pg_conn, owner_user_id)
    owner_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Owner step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    her_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Her step", assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    unassigned_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Unassigned step", assignee_user_id=None, user_id=owner_user_id,
    )

    login(client, member_user_id)
    body = client.get("/tasks").data.decode()

    assert f'action="/tasks/{her_task_id}/toggle"' in body
    assert f'action="/tasks/{owner_task_id}/toggle"' not in body
    assert f'action="/tasks/{unassigned_task_id}/toggle"' not in body

    assert f'action="/strategy-steps/{her_step_id}/toggle"' in body
    assert f'action="/strategy-steps/{owner_step_id}/toggle"' not in body
    assert f'action="/strategy-steps/{unassigned_step_id}/toggle"' not in body


def test_owner_sees_tick_button_for_every_task_and_step(client, pg_conn, owner_user_id, member_user_id):
    owner_task_id = goals_store.create_task(
        pg_conn, title="Owner task", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    her_task_id = goals_store.create_task(
        pg_conn, title="Her task", goal_id=None, assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    unassigned_task_id = goals_store.create_task(
        pg_conn, title="Unassigned task", goal_id=None, assignee_user_id=None, user_id=owner_user_id,
    )

    strategy_id = _make_strategy(pg_conn, owner_user_id)
    owner_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Owner step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    her_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Her step", assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    unassigned_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Unassigned step", assignee_user_id=None, user_id=owner_user_id,
    )

    login(client, owner_user_id)
    body = client.get("/tasks").data.decode()

    for task_id in (owner_task_id, her_task_id, unassigned_task_id):
        assert f'action="/tasks/{task_id}/toggle"' in body
    for step_id in (owner_step_id, her_step_id, unassigned_step_id):
        assert f'action="/strategy-steps/{step_id}/toggle"' in body


def test_member_cannot_toggle_a_task_not_assigned_to_her_via_direct_post(
    client, pg_conn, owner_user_id, member_user_id
):
    task_id = goals_store.create_task(
        pg_conn, title="Owner's", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get("/tasks")
    resp = client.post(f"/tasks/{task_id}/toggle", data={"csrf_token": token(page), "next": "/tasks"})
    assert resp.status_code == 403
    assert goals_store.get_task(pg_conn, task_id)["done"] is False


def test_member_cannot_toggle_a_step_not_assigned_to_her_via_direct_post(
    client, pg_conn, owner_user_id, member_user_id
):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Owner's step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get("/tasks")
    resp = client.post(f"/strategy-steps/{step_id}/toggle", data={"csrf_token": token(page), "next": "/tasks"})
    assert resp.status_code == 403
    assert strategies_store.get_strategy_step(pg_conn, step_id)["done"] is False


def test_member_can_toggle_her_own_task_from_the_tasks_page_and_returns_there(
    client, pg_conn, owner_user_id, member_user_id
):
    task_id = goals_store.create_task(
        pg_conn, title="Hers", goal_id=None, assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get("/tasks")
    resp = client.post(f"/tasks/{task_id}/toggle", data={"csrf_token": token(page), "next": "/tasks"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/tasks"
    assert goals_store.get_task(pg_conn, task_id)["done"] is True


def test_member_can_toggle_her_own_step_from_the_tasks_page_and_returns_there(
    client, pg_conn, owner_user_id, member_user_id
):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Hers", assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get("/tasks")
    resp = client.post(f"/strategy-steps/{step_id}/toggle", data={"csrf_token": token(page), "next": "/tasks"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/tasks"
    assert strategies_store.get_strategy_step(pg_conn, step_id)["done"] is True
