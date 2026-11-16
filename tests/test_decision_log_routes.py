"""
HTTP-level tests for the decision log: both Shannon and Asha can add an
entry, nobody gets an edit/delete route at all, the list page shows newest
first, and it's reachable from the top nav. Needs a real Postgres (skips
without TEST_DATABASE_URL).
"""
import re

import app.decision_log_store as decision_log_store
import app.strategies_store as strategies_store

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m, "expected a csrf_token hidden input on the page"
    return m.group(1)


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def basic_decision_form(**overrides):
    form = {
        "decision_date": "2026-11-02",
        "decision": "Switch mortgage lender",
        "reason": "New rate is 1.2% lower",
        "assumptions": "Rate holds until completion",
    }
    form.update(overrides)
    return form


def test_decisions_page_loads(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    resp = client.get("/decisions")
    assert resp.status_code == 200


def test_owner_can_add_a_decision(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(csrf_token=token(page)))
    assert resp.status_code == 302
    decisions = decision_log_store.list_decisions(pg_conn)
    assert len(decisions) == 1
    assert decisions[0]["created_by_user_id"] == owner_user_id


def test_member_can_also_add_a_decision(client, pg_conn, member_user_id):
    login(client, member_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(csrf_token=token(page)))
    assert resp.status_code == 302
    decisions = decision_log_store.list_decisions(pg_conn)
    assert len(decisions) == 1
    assert decisions[0]["created_by_user_id"] == member_user_id


def test_missing_decision_field_is_rejected(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(decision="", csrf_token=token(page)))
    assert resp.status_code == 400
    assert decision_log_store.list_decisions(pg_conn) == []


def test_missing_reason_field_is_rejected(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(reason="", csrf_token=token(page)))
    assert resp.status_code == 400
    assert decision_log_store.list_decisions(pg_conn) == []


def test_blank_assumptions_is_allowed(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(assumptions="", csrf_token=token(page)))
    assert resp.status_code == 302
    assert decision_log_store.list_decisions(pg_conn)[0]["assumptions"] == ""


def test_no_edit_or_delete_route_exists(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    client.post("/decisions", data=basic_decision_form(csrf_token=token(page)))
    decision_id = decision_log_store.list_decisions(pg_conn)[0]["id"]

    assert client.get(f"/decisions/{decision_id}/edit").status_code == 404
    assert client.post(f"/decisions/{decision_id}/edit", data={"csrf_token": token(page)}).status_code == 404
    assert client.post(f"/decisions/{decision_id}/delete", data={"csrf_token": token(page)}).status_code == 404


def test_list_shows_newest_first(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    client.post("/decisions", data=basic_decision_form(
        decision_date="2026-01-01", decision="Older decision", csrf_token=token(page),
    ))
    page = client.get("/decisions")
    client.post("/decisions", data=basic_decision_form(
        decision_date="2026-11-02", decision="Newer decision", csrf_token=token(page),
    ))
    body = client.get("/decisions").data.decode()
    assert body.find("Newer decision") < body.find("Older decision")


def test_list_shows_both_decision_and_reason_and_assumptions(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    client.post("/decisions", data=basic_decision_form(csrf_token=token(page)))
    body = client.get("/decisions").data.decode()
    assert "Switch mortgage lender" in body
    assert "New rate is 1.2% lower" in body
    assert "Rate holds until completion" in body


def test_login_required_to_view(client, pg_conn):
    resp = client.get("/decisions")
    assert resp.status_code in (302, 401)


def test_post_without_login_is_rejected(client, pg_conn):
    """No session means no valid CSRF token either — rejected before
    login_required ever runs, same as every other POST route
    (test_csrf.py's documented ordering)."""
    resp = client.post("/decisions", data=basic_decision_form(csrf_token="whatever"))
    assert resp.status_code == 400
    assert decision_log_store.list_decisions(pg_conn) == []


def test_decisions_link_is_in_the_top_nav(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert 'href="/decisions"' in body


# ── Optional strategy link (notes & context feature) ─────────────────────

def _make_strategy(pg_conn, owner_user_id, **overrides):
    fields = dict(
        title="Strategy", detail="", area="Business", status="idea",
        work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    fields.update(overrides)
    return strategies_store.create_strategy(pg_conn, **fields)


def test_decision_can_be_linked_to_a_strategy(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(
        strategy_id=str(strategy_id), csrf_token=token(page),
    ))
    assert resp.status_code == 302
    assert decision_log_store.list_decisions(pg_conn)[0]["strategy_id"] == strategy_id


def test_decision_strategy_link_is_optional(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(csrf_token=token(page)))
    assert resp.status_code == 302
    assert decision_log_store.list_decisions(pg_conn)[0]["strategy_id"] is None


def test_decision_can_link_an_archived_strategy(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    strategies_store.archive_strategy(
        pg_conn, strategy_id, reason="No longer relevant", archived_date="2026-11-10", user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(
        strategy_id=str(strategy_id), csrf_token=token(page),
    ))
    assert resp.status_code == 302
    assert decision_log_store.list_decisions(pg_conn)[0]["strategy_id"] == strategy_id


def test_decision_with_a_nonexistent_strategy_id_is_rejected(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(
        strategy_id="999999", csrf_token=token(page),
    ))
    assert resp.status_code == 400
    assert decision_log_store.list_decisions(pg_conn) == []


def test_member_can_also_link_a_strategy_to_her_decision(client, pg_conn, owner_user_id, member_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, member_user_id)
    page = client.get("/decisions")
    resp = client.post("/decisions", data=basic_decision_form(
        strategy_id=str(strategy_id), csrf_token=token(page),
    ))
    assert resp.status_code == 302
    assert decision_log_store.list_decisions(pg_conn)[0]["strategy_id"] == strategy_id


def test_decisions_add_form_has_a_strategy_dropdown(client, pg_conn, owner_user_id):
    _make_strategy(pg_conn, owner_user_id, title="New role — Shannon")
    login(client, owner_user_id)
    body = client.get("/decisions").data.decode()
    assert 'name="strategy_id"' in body
    assert "New role — Shannon" in body


def test_decision_entries_are_width_capped(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/decisions")
    client.post("/decisions", data=basic_decision_form(csrf_token=token(page)))
    body = client.get("/decisions").data.decode()
    assert 'class="card card-narrow"' in body


def test_decision_linked_to_a_strategy_shows_the_strategy_on_the_list(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id, title="New role — Shannon")
    login(client, owner_user_id)
    page = client.get("/decisions")
    client.post("/decisions", data=basic_decision_form(strategy_id=str(strategy_id), csrf_token=token(page)))
    body = client.get("/decisions").data.decode()
    assert f'href="/strategies/{strategy_id}"' in body
    assert "New role — Shannon" in body
