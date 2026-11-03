"""
HTTP-level tests for the decision log: both Shannon and Asha can add an
entry, nobody gets an edit/delete route at all, the list page shows newest
first, and it's reachable from the top nav. Needs a real Postgres (skips
without TEST_DATABASE_URL).
"""
import re

import app.decision_log_store as decision_log_store

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
