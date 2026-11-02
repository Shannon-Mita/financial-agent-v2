"""
HTTP-level tests for Stage 2 Step 4's strategy routes — permissions
(Shannon and Asha add/edit any strategy and its steps, only the assignee
ticks a step, archive and delete owner-only, with a server-side 403 for a
member setting status=archived via the plain edit form), the NULL-vs-zero
regression, and the grouped-by-area display on the Goals page. Needs a
real Postgres (skips without TEST_DATABASE_URL).
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


def basic_strategy_form(**overrides):
    form = {
        "title": "Test strategy",
        "detail": "Some detail",
        "area": "Business",
        "status": "idea",
        "work_lives_in": "here",
        "risks_childcare_eligibility": "unknown",
        "effect_on_net_worth": "",
        "effect_on_passive_income": "",
        "from_when": "",
    }
    form.update(overrides)
    return form


# ── Create: both owner and member allowed ──────────────────────────────

def test_owner_can_create_strategy(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    assert page.status_code == 200
    resp = client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    assert resp.status_code == 302
    assert len(strategies_store.list_strategies(pg_conn)) == 1


def test_member_can_also_create_strategy(client, pg_conn, member_user_id):
    """Unlike every goal/milestone route, strategy creation is NOT
    owner-only (Shannon, 1 Nov 2026)."""
    login(client, member_user_id)
    page = client.get("/strategies/new")
    assert page.status_code == 200
    resp = client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    assert resp.status_code == 302
    strategies = strategies_store.list_strategies(pg_conn)
    assert len(strategies) == 1
    assert strategies[0]["source"] == "asha"


def test_owner_created_strategy_has_source_shannon(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    assert strategies_store.list_strategies(pg_conn)[0]["source"] == "shannon"


# ── Edit: both allowed, including editing each other's ──────────────────

def test_member_can_edit_a_strategy_the_owner_created(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    login(client, member_user_id)
    edit_page = client.get(f"/strategies/{strategy_id}/edit")
    assert edit_page.status_code == 200
    resp = client.post(
        f"/strategies/{strategy_id}/edit",
        data=basic_strategy_form(title="Renamed by Asha", csrf_token=token(edit_page)),
    )
    assert resp.status_code == 302
    assert strategies_store.get_strategy(pg_conn, strategy_id)["title"] == "Renamed by Asha"


# ── Archive/delete: owner only, including the server-side status=archived
# block on the plain edit route ─────────────────────────────────────────

def test_member_gets_403_setting_status_archived_via_plain_edit(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    login(client, member_user_id)
    edit_page = client.get(f"/strategies/{strategy_id}/edit")
    resp = client.post(
        f"/strategies/{strategy_id}/edit",
        data=basic_strategy_form(status="archived", csrf_token=token(edit_page)),
    )
    assert resp.status_code == 403
    assert strategies_store.get_strategy(pg_conn, strategy_id)["status"] == "idea"


def test_member_does_not_see_archived_as_an_option_in_her_edit_form(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    login(client, member_user_id)
    body = client.get(f"/strategies/{strategy_id}/edit").data.decode()
    assert 'value="archived"' not in body


def test_owner_sees_archived_as_an_option(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]
    body = client.get(f"/strategies/{strategy_id}/edit").data.decode()
    assert 'value="archived"' in body


def test_member_gets_403_on_archive_route(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    login(client, member_user_id)
    confirm_page = client.get(f"/strategies/{strategy_id}/archive-confirm")
    assert confirm_page.status_code == 403
    valid_token = token(client.get("/goals"))  # a real token from a page she CAN access
    resp = client.post(f"/strategies/{strategy_id}/archive", data={"reason": "done", "csrf_token": valid_token})
    assert resp.status_code == 403


def test_owner_can_archive_with_reason(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    confirm_page = client.get(f"/strategies/{strategy_id}/archive-confirm")
    assert confirm_page.status_code == 200
    resp = client.post(
        f"/strategies/{strategy_id}/archive",
        data={"reason": "No longer relevant", "csrf_token": token(confirm_page)},
    )
    assert resp.status_code == 302
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["status"] == "archived"
    assert s["archived_reason"] == "No longer relevant"
    assert s["archived_date"] is not None


def test_archived_strategy_drops_off_the_active_goals_page_list(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(title="Archive me", csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    confirm_page = client.get(f"/strategies/{strategy_id}/archive-confirm")
    client.post(f"/strategies/{strategy_id}/archive", data={"reason": "done", "csrf_token": token(confirm_page)})

    body = client.get("/goals").data.decode()
    assert "Archive me" not in body


def test_member_gets_403_deleting_a_strategy(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    login(client, member_user_id)
    valid_token = token(client.get("/goals"))
    resp = client.post(f"/strategies/{strategy_id}/delete", data={"csrf_token": valid_token})
    assert resp.status_code == 403
    assert strategies_store.get_strategy(pg_conn, strategy_id) is not None


def test_owner_can_delete_a_strategy(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    confirm_page = client.get(f"/strategies/{strategy_id}/delete-confirm")
    assert confirm_page.status_code == 200
    resp = client.post(f"/strategies/{strategy_id}/delete", data={"csrf_token": token(confirm_page)})
    assert resp.status_code == 302
    assert strategies_store.get_strategy(pg_conn, strategy_id) is None


# ── NULL-vs-zero regression ──────────────────────────────────────────────

def test_blank_effect_fields_store_null_shown_as_question_mark(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(
        effect_on_net_worth="", effect_on_passive_income="", csrf_token=token(page),
    ))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["effect_on_net_worth"] is None
    assert s["effect_on_passive_income"] is None

    body = client.get("/goals").data.decode()
    assert "?" in body


def test_explicit_zero_effect_stores_the_number_zero_not_null(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(
        title="Mahired / Welfound", effect_on_net_worth="0", effect_on_passive_income="0",
        csrf_token=token(page),
    ))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]
    s = strategies_store.get_strategy(pg_conn, strategy_id)
    assert s["effect_on_net_worth"] == 0
    assert s["effect_on_passive_income"] == 0
    # A real zero must render as "0", never silently merged with "?" unknowns.
    body = client.get(f"/strategies/{strategy_id}").data.decode()
    assert "£0" in body


def test_zero_and_unknown_are_never_confused_on_the_goals_page(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page1 = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(
        title="Known zero", effect_on_net_worth="0", csrf_token=token(page1),
    ))
    page2 = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(
        title="Unknown effect", effect_on_net_worth="", csrf_token=token(page2),
    ))
    strategies = {s["title"]: s for s in strategies_store.list_strategies(pg_conn)}
    assert strategies["Known zero"]["effect_on_net_worth"] == 0
    assert strategies["Unknown effect"]["effect_on_net_worth"] is None


# ── Grouped by area, effects/status/last-reviewed/"?"/staleness on the
# Goals page ──────────────────────────────────────────────────────────────

def test_strategies_grouped_by_area_on_goals_page(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    for title, area in (("New role", "Work and income"), ("Crypto", "Investing")):
        page = client.get("/strategies/new")
        client.post("/strategies", data=basic_strategy_form(title=title, area=area, csrf_token=token(page)))

    body = client.get("/goals").data.decode()
    assert "Work and income" in body
    assert "Investing" in body
    assert body.find("Work and income") < body.find("New role")
    assert body.find("Investing") < body.find("Crypto")


def test_strategy_card_shows_status_and_risks_childcare_eligibility(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(
        title="New role", status="in progress", risks_childcare_eligibility="yes", csrf_token=token(page),
    ))
    body = client.get("/goals").data.decode()
    assert "in progress" in body
    assert "risks childcare eligibility" in body.lower() or "childcare" in body.lower()


def test_strategy_card_shows_stale_badge_when_never_reviewed(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(title="Needs review", csrf_token=token(page)))
    body = client.get("/goals").data.decode()
    assert 'class="badge stale"' in body


def test_strategy_card_not_stale_when_reviewed_recently(client, pg_conn, owner_user_id):
    from datetime import date

    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]
    edit_page = client.get(f"/strategies/{strategy_id}/edit")
    client.post(f"/strategies/{strategy_id}/edit", data=basic_strategy_form(
        last_reviewed_date=date.today().isoformat(), csrf_token=token(edit_page),
    ))
    body = client.get("/goals").data.decode()
    assert 'class="badge stale"' not in body


# ── Steps ─────────────────────────────────────────────────────────────────

def test_either_person_can_create_a_step_on_any_strategy(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]

    login(client, member_user_id)
    detail_page = client.get(f"/strategies/{strategy_id}")
    resp = client.post("/strategy-steps", data={
        "strategy_id": str(strategy_id), "title": "Open an account",
        "assignee_user_id": str(member_user_id), "csrf_token": token(detail_page),
    })
    assert resp.status_code == 302
    steps = strategies_store.list_strategy_steps(pg_conn, strategy_id)
    assert len(steps) == 1


def test_owner_can_toggle_any_step_member_only_her_own(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    client.post("/strategies", data=basic_strategy_form(csrf_token=token(page)))
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Open an account",
        assignee_user_id=owner_user_id, user_id=owner_user_id,
    )

    login(client, member_user_id)
    detail_page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategy-steps/{step_id}/toggle", data={"csrf_token": token(detail_page)})
    assert resp.status_code == 403

    login(client, owner_user_id)
    detail_page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategy-steps/{step_id}/toggle", data={"csrf_token": token(detail_page)})
    assert resp.status_code == 302
    assert strategies_store.get_strategy_step(pg_conn, step_id)["done"] is True


# ── Lever dimension validated app-side against a curated set ────────────

def test_lever_dimension_must_be_a_known_fact_key(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    resp = client.post("/strategies", data=basic_strategy_form(
        lever_dimension="not.a.real.fact.key", lever_delta="1000", lever_from_date="2027-01-01",
        csrf_token=token(page),
    ))
    assert resp.status_code == 400


def test_lever_with_known_fact_key_dimension_is_accepted(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/strategies/new")
    resp = client.post("/strategies", data=basic_strategy_form(
        lever_dimension="income.shannon.paye_salary", lever_delta="10000", lever_from_date="2027-01-01",
        csrf_token=token(page),
    ))
    assert resp.status_code == 302
    strategy_id = strategies_store.list_strategies(pg_conn)[0]["id"]
    levers = strategies_store.list_strategy_levers(pg_conn, strategy_id)
    assert len(levers) == 1
    assert levers[0]["dimension"] == "income.shannon.paye_salary"
