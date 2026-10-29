"""
CSRF enforcement and cookie hardening (Shannon's amendment #3). The missing-
token test needs no database — CSRF is checked before the view (and before
auth) ever runs. The full-flow test (valid token actually gets accepted)
needs a real Postgres, since it exercises login + a real fact write.
"""
import re

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def test_cookie_flags_are_hardened(app):
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_post_without_csrf_token_is_rejected(client):
    resp = client.post("/facts/income.shannon.paye_salary/update", data={"value": "123"})
    assert resp.status_code == 400


def test_valid_csrf_token_update_succeeds_end_to_end(app, client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 1, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )

    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner_user_id)

    page = client.get("/")
    token_match = TOKEN_RE.search(page.data.decode())
    assert token_match, "expected a csrf_token hidden input on the dashboard"
    token = token_match.group(1)

    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"value": "60000", "csrf_token": token},
    )
    assert resp.status_code == 204
    assert store.get("income.shannon.paye_salary").value == 60000
