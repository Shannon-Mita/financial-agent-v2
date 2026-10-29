"""
Live-site bug: every POST form (confirm, update) returned 400 "The
referrer header is missing" over HTTPS. Cause: Referrer-Policy: no-referrer
told browsers to never send a Referer, including on same-origin form
submissions — but Flask-WTF's WTF_CSRF_SSL_STRICT (default True, and NOT
being weakened here) requires a same-origin Referer on every HTTPS POST.
Fix: Referrer-Policy: same-origin — browsers still send Referer for
same-origin requests (satisfying the CSRF check) while never leaking it
cross-origin.

These tests simulate HTTPS explicitly via base_url, since the bug only
manifests when request.is_secure is True (the test client defaults to
plain HTTP, which is why this never showed up in earlier CSRF tests).
"""
import re

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

HTTPS_BASE = "https://localhost"
TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def seed_and_login(pg_conn, client, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 1, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    return store


def get_token(client):
    page = client.get("/", base_url=HTTPS_BASE)
    return TOKEN_RE.search(page.data.decode()).group(1)


def test_https_post_with_no_referer_still_fails_csrf_not_weakened(client, pg_conn, owner_user_id):
    """Must keep failing — this is WTF_CSRF_SSL_STRICT doing its job on a
    genuinely missing Referer. The fix must not touch this."""
    seed_and_login(pg_conn, client, owner_user_id)
    token = get_token(client)

    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        base_url=HTTPS_BASE,
        data={"value": "60000", "csrf_token": token},
    )
    assert resp.status_code == 400
    assert b"referrer" in resp.data.lower()


def test_https_post_with_same_origin_referer_succeeds(client, pg_conn, owner_user_id):
    """The real browser behaviour this bug broke: a normal same-origin form
    POST (which sends a same-origin Referer under Referrer-Policy:
    same-origin) must succeed, not 400."""
    store = seed_and_login(pg_conn, client, owner_user_id)
    token = get_token(client)

    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        base_url=HTTPS_BASE,
        data={"value": "60000", "csrf_token": token},
        headers={"Referer": f"{HTTPS_BASE}/"},
    )
    assert resp.status_code == 204
    assert store.get("income.shannon.paye_salary").value == 60000


def test_https_confirm_with_same_origin_referer_succeeds(client, pg_conn, owner_user_id):
    seed_and_login(pg_conn, client, owner_user_id)
    token = get_token(client)

    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        base_url=HTTPS_BASE,
        data={"csrf_token": token},
        headers={"Referer": f"{HTTPS_BASE}/"},
    )
    assert resp.status_code == 204


def test_https_confirm_with_no_referer_still_fails_csrf_not_weakened(client, pg_conn, owner_user_id):
    seed_and_login(pg_conn, client, owner_user_id)
    token = get_token(client)

    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        base_url=HTTPS_BASE,
        data={"csrf_token": token},
    )
    assert resp.status_code == 400


def test_referrer_policy_header_is_same_origin(client):
    resp = client.get("/login")
    assert resp.headers["Referrer-Policy"] == "same-origin"
