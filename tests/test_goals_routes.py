"""
HTTP-level tests for Stage 1's goal/task routes — every row of the
permission matrix exercised over the real route, not just the pure
permission functions in isolation (those live in test_permissions.py).
Needs a real Postgres (skips without TEST_DATABASE_URL).
"""
import re

import psycopg2
import pytest

import app.goals_store as goals_store
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m, "expected a csrf_token hidden input on the page"
    return m.group(1)


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def basic_goal_form(**overrides):
    form = {
        "title": "Test goal",
        "type": "binary",
        "target_value_mode": "amount",
        "target_date_mode": "date",
    }
    form.update(overrides)
    return form


# ── Unauthenticated / non-allowlisted ──────────────────────────────────────

def test_unauthenticated_get_goals_redirects_to_login(client):
    resp = client.get("/goals")
    assert resp.status_code == 302


@pytest.mark.parametrize("path,method", [
    ("/goals", "post"),
    ("/goals/1/edit", "post"),
    ("/goals/1/delete", "post"),
    ("/goals/1/status", "post"),
    ("/tasks", "post"),
    ("/tasks/1/edit", "post"),
    ("/tasks/1/delete", "post"),
    ("/tasks/1/toggle", "post"),
])
def test_unauthenticated_post_is_rejected(client, path, method):
    resp = getattr(client, method)(path)
    assert resp.status_code in (302, 400, 401)  # redirected to login or CSRF-rejected first


# ── Goal CRUD: owner yes, member no ────────────────────────────────────────

def test_owner_can_create_goal(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    assert page.status_code == 200
    resp = client.post("/goals", data=basic_goal_form(csrf_token=token(page)))
    assert resp.status_code == 302
    assert len(goals_store.list_goals(pg_conn)) == 1


def test_member_cannot_create_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    t = token(page)

    login(client, member_user_id)
    resp = client.post("/goals", data=basic_goal_form(csrf_token=t))
    assert resp.status_code == 403
    assert goals_store.list_goals(pg_conn) == []


def test_member_cannot_get_new_goal_form(client, member_user_id):
    login(client, member_user_id)
    resp = client.get("/goals/new")
    assert resp.status_code == 403


def test_owner_can_edit_goal(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Orig", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    page = client.get(f"/goals/{goal_id}/edit")
    assert page.status_code == 200
    resp = client.post(f"/goals/{goal_id}/edit", data=basic_goal_form(title="Renamed", csrf_token=token(page)))
    assert resp.status_code == 302
    assert goals_store.get_goal(pg_conn, goal_id)["title"] == "Renamed"


def test_member_cannot_edit_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Orig", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    page = client.get("/goals")
    t = token(page)

    login(client, member_user_id)
    resp = client.post(f"/goals/{goal_id}/edit", data=basic_goal_form(title="Hacked", csrf_token=t))
    assert resp.status_code == 403
    assert goals_store.get_goal(pg_conn, goal_id)["title"] == "Orig"

    get_resp = client.get(f"/goals/{goal_id}/edit")
    assert get_resp.status_code == 403


def test_owner_can_delete_goal(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Orig", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    page = client.get("/goals")
    resp = client.post(f"/goals/{goal_id}/delete", data={"csrf_token": token(page)})
    assert resp.status_code == 302
    assert goals_store.get_goal(pg_conn, goal_id) is None


def test_member_cannot_delete_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Orig", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    page = client.get("/goals")
    t = token(page)

    login(client, member_user_id)
    resp = client.post(f"/goals/{goal_id}/delete", data={"csrf_token": t})
    assert resp.status_code == 403
    assert goals_store.get_goal(pg_conn, goal_id) is not None


def test_owner_delete_blocked_while_sub_goals_exist(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    parent_id = goals_store.create_goal(
        pg_conn, title="Parent", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    goals_store.create_goal(
        pg_conn, title="Child", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=parent_id,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    page = client.get("/goals")
    resp = client.post(f"/goals/{parent_id}/delete", data={"csrf_token": token(page)})
    assert resp.status_code == 400
    assert goals_store.get_goal(pg_conn, parent_id) is not None


# ── Goal "never both" fact-backed/local target ────────────────────────────

def test_fact_backed_target_must_be_from_known_registry(client, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    resp = client.post("/goals", data=basic_goal_form(
        type="target", target_value_mode="fact", source_fact_key="income.shannon.paye_salary",
        csrf_token=token(page),
    ))
    assert resp.status_code == 400


def test_fact_backed_target_date_must_be_from_known_registry(client, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    resp = client.post("/goals", data=basic_goal_form(
        type="target", target_date_mode="fact", target_date_fact_key="cashflow.monthly_essentials",
        csrf_token=token(page),
    ))
    assert resp.status_code == 400


def test_fire_goal_fact_backed_target_and_date_from_registry_succeeds(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    resp = client.post("/goals", data=basic_goal_form(
        type="target", target_value_mode="fact", source_fact_key="goals.fire.target_number",
        target_date_mode="fact", target_date_fact_key="goals.fire.target_date",
        csrf_token=token(page),
    ))
    assert resp.status_code == 302
    goal = goals_store.list_goals(pg_conn)[0]
    assert goal["target_value"] is None and goal["source_fact_key"] == "goals.fire.target_number"
    assert goal["target_date"] is None and goal["target_date_fact_key"] == "goals.fire.target_date"


def test_store_level_check_still_rejects_dual_target_even_bypassing_the_form(pg_conn, owner_user_id):
    """Belt-and-suspenders: even if app code were buggy and called the store
    directly with both set, the DB CHECK constraint (migrations/002) refuses it."""
    with pytest.raises(psycopg2.errors.CheckViolation):
        goals_store.create_goal(
            pg_conn, title="Bad", type="target", target_value=1000,
            target_date=None, source_fact_key="goals.fire.target_number",
            target_date_fact_key=None, progress_fact_keys=None,
            cadence_period=None, cadence_amount=None, parent_id=None,
            assignee_user_ids=[], user_id=owner_user_id,
        )
    pg_conn.rollback()


def test_progress_fact_keys_must_already_exist(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("savings.house_deposit.balance", 1000, Unit.GBP, Source.USER_STATED, "balance"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/goals/new")
    resp = client.post("/goals", data=basic_goal_form(
        progress_fact_keys="made.up.key", csrf_token=token(page),
    ))
    assert resp.status_code == 400

    resp_ok = client.post("/goals", data=basic_goal_form(
        progress_fact_keys="savings.house_deposit.balance", csrf_token=token(client.get("/goals")),
    ))
    assert resp_ok.status_code == 302


# ── Goal status toggling (binary/habit, assignee-only for members) ───────

def test_member_can_toggle_status_of_her_assigned_binary_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Her goal", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get(f"/goals/{goal_id}")
    resp = client.post(f"/goals/{goal_id}/status", data={"csrf_token": token(page)})
    assert resp.status_code == 302
    assert goals_store.get_goal(pg_conn, goal_id)["status"] == "done"


def test_member_cannot_toggle_status_of_unassigned_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Not hers", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    page = client.get("/goals")
    t = token(page)
    login(client, member_user_id)
    resp = client.post(f"/goals/{goal_id}/status", data={"csrf_token": t})
    assert resp.status_code == 403
    assert goals_store.get_goal(pg_conn, goal_id)["status"] == "active"


def test_member_cannot_toggle_status_of_assigned_target_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Target goal", type="target", target_value=1000,
        target_date="2030-01-01", source_fact_key=None, target_date_fact_key=None,
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    page = client.get("/goals")
    t = token(page)
    login(client, member_user_id)
    resp = client.post(f"/goals/{goal_id}/status", data={"csrf_token": t})
    assert resp.status_code == 403


def test_owner_can_toggle_status_of_any_goal(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Hers", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    page = client.get(f"/goals/{goal_id}")
    resp = client.post(f"/goals/{goal_id}/status", data={"csrf_token": token(page)})
    assert resp.status_code == 302
    assert goals_store.get_goal(pg_conn, goal_id)["status"] == "done"


# ── Tasks: create / edit / delete / toggle ────────────────────────────────

def test_member_can_create_task_assigned_to_herself(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    t = token(page)
    login(client, member_user_id)
    resp = client.post("/tasks", data={
        "csrf_token": t, "title": "My task", "assignee_user_id": str(member_user_id),
    })
    assert resp.status_code == 302
    tasks = goals_store.list_tasks(pg_conn)
    assert len(tasks) == 1 and tasks[0]["assignee_user_id"] == member_user_id


def test_member_cannot_create_task_for_owner(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    t = token(page)
    login(client, member_user_id)
    resp = client.post("/tasks", data={
        "csrf_token": t, "title": "For him", "assignee_user_id": str(owner_user_id),
    })
    assert resp.status_code == 403
    assert goals_store.list_tasks(pg_conn) == []


def test_member_cannot_create_unassigned_task(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    t = token(page)
    login(client, member_user_id)
    resp = client.post("/tasks", data={"csrf_token": t, "title": "Floating"})
    assert resp.status_code == 403


def test_owner_can_create_task_for_anyone_or_unassigned(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    resp = client.post("/tasks", data={
        "csrf_token": token(page), "title": "For partner", "assignee_user_id": str(member_user_id),
    })
    assert resp.status_code == 302
    page = client.get("/goals")
    resp2 = client.post("/tasks", data={"csrf_token": token(page), "title": "Unassigned"})
    assert resp2.status_code == 302
    assert len(goals_store.list_tasks(pg_conn)) == 2


def test_member_can_edit_or_delete_only_her_own_task(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    t = token(page)
    login(client, member_user_id)
    client.post("/tasks", data={"csrf_token": t, "title": "Hers", "assignee_user_id": str(member_user_id)})
    task_id = goals_store.list_tasks(pg_conn)[0]["id"]

    page = client.get("/goals")
    resp = client.post(f"/tasks/{task_id}/edit", data={
        "csrf_token": token(page), "title": "Renamed", "assignee_user_id": str(member_user_id),
    })
    assert resp.status_code == 302
    assert goals_store.get_task(pg_conn, task_id)["title"] == "Renamed"

    page = client.get("/goals")
    resp = client.post(f"/tasks/{task_id}/delete", data={"csrf_token": token(page)})
    assert resp.status_code == 302
    assert goals_store.get_task(pg_conn, task_id) is None


def test_member_cannot_edit_or_delete_a_task_created_by_owner_even_if_assigned_to_her(
    client, pg_conn, owner_user_id, member_user_id
):
    login(client, owner_user_id)
    page = client.get("/goals")
    client.post("/tasks", data={
        "csrf_token": token(page), "title": "Assigned to her", "assignee_user_id": str(member_user_id),
    })
    task_id = goals_store.list_tasks(pg_conn)[0]["id"]

    login(client, member_user_id)
    page = client.get("/goals")
    resp = client.post(f"/tasks/{task_id}/edit", data={
        "csrf_token": token(page), "title": "Hacked", "assignee_user_id": str(member_user_id),
    })
    assert resp.status_code == 403

    resp = client.post(f"/tasks/{task_id}/delete", data={"csrf_token": token(client.get('/goals'))})
    assert resp.status_code == 403
    assert goals_store.get_task(pg_conn, task_id) is not None


def test_member_can_toggle_only_her_own_assigned_task(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    client.post("/tasks", data={
        "csrf_token": token(page), "title": "Hers", "assignee_user_id": str(member_user_id),
    })
    page = client.get("/goals")
    client.post("/tasks", data={
        "csrf_token": token(page), "title": "His", "assignee_user_id": str(owner_user_id),
    })
    page = client.get("/goals")
    client.post("/tasks", data={"csrf_token": token(page), "title": "Unassigned"})

    tasks = {t["title"]: t["id"] for t in goals_store.list_tasks(pg_conn)}

    login(client, member_user_id)
    page = client.get("/goals")
    resp = client.post(f"/tasks/{tasks['Hers']}/toggle", data={"csrf_token": token(page)})
    assert resp.status_code == 302
    assert goals_store.get_task(pg_conn, tasks["Hers"])["done"] is True

    page = client.get("/goals")
    resp = client.post(f"/tasks/{tasks['His']}/toggle", data={"csrf_token": token(page)})
    assert resp.status_code == 403

    page = client.get("/goals")
    resp = client.post(f"/tasks/{tasks['Unassigned']}/toggle", data={"csrf_token": token(page)})
    assert resp.status_code == 403


def test_owner_can_toggle_any_task(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    client.post("/tasks", data={
        "csrf_token": token(page), "title": "Hers", "assignee_user_id": str(member_user_id),
    })
    task_id = goals_store.list_tasks(pg_conn)[0]["id"]
    page = client.get("/goals")
    resp = client.post(f"/tasks/{task_id}/toggle", data={"csrf_token": token(page)})
    assert resp.status_code == 302
    assert goals_store.get_task(pg_conn, task_id)["done"] is True


# ── Audit trail ────────────────────────────────────────────────────────────

def test_goal_and_task_mutations_write_audit_log_rows(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    client.post("/goals", data=basic_goal_form(csrf_token=token(page)))
    goal_id = goals_store.list_goals(pg_conn)[0]["id"]

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM audit_log WHERE entity_type = 'goal' AND entity_id = %s", (goal_id,)
        )
        events = [r[0] for r in cur.fetchall()]
    assert events == ["created"]

    page = client.get("/goals")
    client.post(f"/goals/{goal_id}/status", data={"csrf_token": token(page)})
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM audit_log WHERE entity_type = 'goal' AND entity_id = %s ORDER BY id",
            (goal_id,),
        )
        events = [r[0] for r in cur.fetchall()]
    assert events == ["created", "status_changed"]


# ── Golden-path render smoke tests (catches template errors, not just logic) ─

def test_goals_list_renders_fire_breakdown_and_feasibility(client, pg_conn, owner_user_id, member_user_id):
    store = PostgresFactStore(pg_conn)
    seed_facts = [
        ("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
        ("income.partner.paye_salary", 70000, Unit.GBP_PER_YEAR, "income"),
        ("cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_childcare", 600, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_other", 200, Unit.GBP_PER_MONTH, "spending"),
        ("savings.house_deposit.balance", 22000, Unit.GBP, "balance"),
        ("isa.shannon.cash.value", 5000, Unit.GBP, "balance"),
        ("isa.shannon.stocks_shares.value", 40000, Unit.GBP, "balance"),
        ("isa.partner.cash.value", 3000, Unit.GBP, "balance"),
        ("isa.partner.stocks_shares.value", 20000, Unit.GBP, "balance"),
        ("investments.partner.stocks_gia_value", 10000, Unit.GBP, "balance"),
        ("investments.shannon.crypto_value", 2000, Unit.GBP, "balance"),
        ("pensions.shannon.current_value", 150000, Unit.GBP, "pension"),
        ("pensions.partner.current_value", 90000, Unit.GBP, "pension"),
        ("goals.fire.target_number", 2_400_000, Unit.GBP, "goal"),
        ("goals.fire.target_date", "2030-10-05", Unit.DATE, "goal"),
    ]
    for key, val, unit, cat in seed_facts:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat), owner="joint", entered_by_user_id=owner_user_id)

    fire_id = goals_store.create_goal(
        pg_conn, title="FIRE", type="target", target_value=None, target_date=None,
        source_fact_key="goals.fire.target_number", target_date_fact_key="goals.fire.target_date",
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id, member_user_id], user_id=owner_user_id,
    )
    goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-08-29",
        source_fact_key=None, target_date_fact_key=None,
        progress_fact_keys=["savings.house_deposit.balance"], cadence_period=None, cadence_amount=None,
        parent_id=fire_id, assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )

    login(client, owner_user_id)
    resp = client.get("/goals")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "FIRE" in body and "House deposit" in body
    assert "locked" in body  # pensions badge
    assert "short" in body.lower()  # the deposit goal is short per the golden maths

    detail = client.get(f"/goals/{fire_id}")
    assert detail.status_code == 200
    assert "Accessible total" in detail.data.decode()


def test_feasibility_card_renders_straight_line_caveat(client, pg_conn, owner_user_id, member_user_id):
    store = PostgresFactStore(pg_conn)
    for key, val, unit, cat in [
        ("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
        ("income.partner.paye_salary", 70000, Unit.GBP_PER_YEAR, "income"),
        ("cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_childcare", 600, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_other", 200, Unit.GBP_PER_MONTH, "spending"),
        ("savings.house_deposit.balance", 22000, Unit.GBP, "balance"),
    ]:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat), owner="joint", entered_by_user_id=owner_user_id)

    goal_id = goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-08-29",
        source_fact_key=None, target_date_fact_key=None,
        progress_fact_keys=["savings.house_deposit.balance"], cadence_period=None, cadence_amount=None,
        parent_id=None, assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )

    login(client, owner_user_id)
    resp = client.get(f"/goals/{goal_id}")
    body = resp.data.decode()
    assert "straight-line" in body
    assert "no investment growth" in body
    assert "no inflation" in body
    assert "no tax on investment gains" in body


# ── "Not yet set" section on the Numbers page ─────────────────────────────

def test_owner_sees_not_yet_set_section_with_correct_input_types(client, owner_user_id):
    login(client, owner_user_id)
    resp = client.get("/")
    body = resp.data.decode()
    assert "Not yet set" in body
    assert 'action="/facts/goals.fire.target_date/update"' in body
    assert 'action="/facts/savings.house_deposit.balance/update"' in body
    # crude but sufficient: the date-typed input appears before the GBP one
    # closes, i.e. each form has its own correctly-typed input somewhere
    assert 'type="date"' in body
    assert 'type="number"' in body


def test_owner_can_create_each_registered_key_through_the_not_yet_set_form(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    login(client, owner_user_id)

    page = client.get("/")
    resp = client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2030-10-05", "csrf_token": token(page)},
    )
    assert resp.status_code == 204
    assert store.get("goals.fire.target_date").value == "2030-10-05"

    page = client.get("/")
    resp = client.post(
        "/facts/savings.house_deposit.balance/update",
        data={"value": "22000", "csrf_token": token(page)},
    )
    assert resp.status_code == 204
    assert store.get("savings.house_deposit.balance").value == 22000


def test_created_key_moves_from_not_yet_set_into_the_normal_list(client, owner_user_id):
    # "Set <key>" is the not-yet-set form's own button label — unique to
    # that form (the normal row's buttons say "Confirm still correct" /
    # "Update"), so its presence/absence unambiguously tells us which
    # section the key is currently rendered in.
    login(client, owner_user_id)
    before = client.get("/").data.decode()
    assert "Set goals.fire.target_date" in before

    page = client.get("/")
    client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2030-10-05", "csrf_token": token(page)},
    )

    after = client.get("/").data.decode()
    assert "Set goals.fire.target_date" not in after  # no longer in "Not yet set"
    assert "goals.fire.target_date" in after          # now in the normal list
    assert "2030-10-05" in after


def test_member_does_not_see_not_yet_set_section_or_its_forms(client, member_user_id):
    login(client, member_user_id)
    resp = client.get("/")
    body = resp.data.decode()
    assert "Not yet set" not in body
    assert 'action="/facts/goals.fire.target_date/update"' not in body
    assert 'action="/facts/savings.house_deposit.balance/update"' not in body


def test_member_crafted_post_to_not_yet_set_route_is_403(client, pg_conn, member_user_id):
    store = PostgresFactStore(pg_conn)
    login(client, member_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2030-10-05", "csrf_token": token(page)},
    )
    assert resp.status_code == 403
    assert store.get("goals.fire.target_date") is None


def test_partner_can_update_house_deposit_balance_once_it_exists_but_never_goals_keys(
    client, pg_conn, owner_user_id, member_user_id
):
    store = PostgresFactStore(pg_conn)
    login(client, owner_user_id)
    page = client.get("/")
    client.post(
        "/facts/savings.house_deposit.balance/update",
        data={"value": "22000", "csrf_token": token(page)},
    )
    page = client.get("/")
    client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2030-10-05", "csrf_token": token(page)},
    )

    login(client, member_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/savings.house_deposit.balance/update",
        data={"value": "25000", "csrf_token": token(page)},
    )
    assert resp.status_code == 204
    assert store.get("savings.house_deposit.balance").value == 25000

    page = client.get("/")
    resp = client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2031-01-01", "csrf_token": token(page)},
    )
    assert resp.status_code == 403
    assert store.get("goals.fire.target_date").value == "2030-10-05"  # unchanged


# ── Server-side delete-confirmation pages (no inline JS — CSP forbids it) ──

def test_goal_delete_confirm_page_shows_goal_and_consequences(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-06-30",
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    goals_store.create_task(
        pg_conn, title="Open a LISA", goal_id=goal_id, assignee_user_id=member_user_id, user_id=owner_user_id,
    )

    resp = client.get(f"/goals/{goal_id}/delete-confirm")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "House deposit" in body
    assert "Open a LISA" in body  # the task that would be deleted too
    assert f'action="{"/goals/%d/delete" % goal_id}"' in body
    assert "csrf_token" in body
    assert "Cancel" in body


def test_goal_delete_confirm_blocked_when_sub_goals_exist(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    parent_id = goals_store.create_goal(
        pg_conn, title="Parent", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    goals_store.create_goal(
        pg_conn, title="Child", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=parent_id,
        assignee_user_ids=[], user_id=owner_user_id,
    )

    resp = client.get(f"/goals/{parent_id}/delete-confirm")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "sub-goal" in body.lower()
    assert f'action="/goals/{parent_id}/delete"' not in body  # no delete form offered


def test_goal_delete_confirm_requires_owner(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Goal", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    login(client, member_user_id)
    resp = client.get(f"/goals/{goal_id}/delete-confirm")
    assert resp.status_code == 403


def test_goal_delete_confirm_requires_login(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Goal", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    with client.session_transaction() as sess:
        sess.pop("_user_id", None)
    resp = client.get(f"/goals/{goal_id}/delete-confirm")
    assert resp.status_code == 302


def test_goal_detail_delete_button_links_to_confirm_page_not_a_direct_post(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    goal_id = goals_store.create_goal(
        pg_conn, title="Goal", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[], user_id=owner_user_id,
    )
    body = client.get(f"/goals/{goal_id}").data.decode()
    assert f'href="/goals/{goal_id}/delete-confirm"' in body
    assert f'action="/goals/{goal_id}/delete"' not in body  # no direct-delete form on the detail page


def test_task_delete_confirm_page_shows_task(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    task_id = goals_store.create_task(
        pg_conn, title="My task", goal_id=None, assignee_user_id=member_user_id, user_id=owner_user_id,
    )
    resp = client.get(f"/tasks/{task_id}/delete-confirm")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "My task" in body
    assert f'action="/tasks/{task_id}/delete"' in body
    assert "csrf_token" in body
    assert "Cancel" in body


def test_task_delete_confirm_requires_permission(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    task_id = goals_store.create_task(
        pg_conn, title="His task", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    resp = client.get(f"/tasks/{task_id}/delete-confirm")
    assert resp.status_code == 403


def test_task_delete_confirm_allows_member_for_her_own_task(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    client.post("/tasks", data={
        "csrf_token": token(page), "title": "Hers", "assignee_user_id": str(member_user_id),
    })
    login(client, member_user_id)
    page = client.get("/goals")
    client.post("/tasks", data={"csrf_token": token(page), "title": "Her own", "assignee_user_id": str(member_user_id)})
    task_id = [t for t in goals_store.list_tasks(pg_conn) if t["title"] == "Her own"][0]["id"]

    resp = client.get(f"/tasks/{task_id}/delete-confirm")
    assert resp.status_code == 200


def test_goals_list_task_delete_links_to_confirm_page(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    task_id = goals_store.create_task(
        pg_conn, title="Standalone", goal_id=None, assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    body = client.get("/goals").data.decode()
    assert f'href="/tasks/{task_id}/delete-confirm"' in body
    assert f'action="/tasks/{task_id}/delete"' not in body
