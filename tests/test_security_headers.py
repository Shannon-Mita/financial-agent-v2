"""
Security response headers on every response, plus Cache-Control: no-store
while authenticated. The unauthenticated checks need no DB; the
authenticated ones need a real Postgres (skip without TEST_DATABASE_URL).
"""
import re

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def test_security_headers_present_on_unauthenticated_response(client):
    resp = client.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in resp.headers["Content-Security-Policy"]


def test_no_store_absent_when_not_authenticated(client):
    resp = client.get("/manifest.webmanifest")
    assert "Cache-Control" not in resp.headers or "no-store" not in resp.headers.get("Cache-Control", "")


def test_no_store_present_once_authenticated(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    resp = client.get("/")
    assert resp.headers["Cache-Control"] == "no-store"


def test_no_store_present_on_goals_page_once_authenticated(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    resp = client.get("/goals")
    assert resp.headers["Cache-Control"] == "no-store"


def test_security_headers_do_not_break_dashboard_update_flow(client, pg_conn, owner_user_id):
    """Regression guard: the strict CSP must not stop the existing
    confirm/update forms from working — they're plain HTML forms, no JS,
    so a strict script-src should have zero effect on them."""
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 1, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    token = TOKEN_RE.search(page.data.decode()).group(1)
    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"value": "60000", "csrf_token": token},
    )
    assert resp.status_code == 303


def test_no_inline_style_attributes_remain_in_any_template():
    """A strict style-src 'self' (no 'unsafe-inline') silently no-ops any
    inline style="..." attribute — this guards against one creeping back in
    and quietly breaking layout instead of failing loudly."""
    import glob
    import os

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    for path in glob.glob(os.path.join(templates_dir, "**", "*.html"), recursive=True):
        with open(path) as f:
            assert 'style="' not in f.read(), f"inline style attribute found in {path}"


def test_no_inline_event_handler_attributes_remain_in_any_template():
    import glob
    import os
    import re as re_mod

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    handler_re = re_mod.compile(r'\son[a-z]+="')
    for path in glob.glob(os.path.join(templates_dir, "**", "*.html"), recursive=True):
        with open(path) as f:
            content = f.read()
        assert not handler_re.search(content), f"inline event handler found in {path}"
