"""
New hypothesis for the live-site 405: a session's login state expires (the
Flask session cookie itself is still valid — csrf_token intact — but
`_user_id` no longer resolves to a logged-in user). Clicking Confirm on a
POST-only URL like /facts/<key>/confirm then hits @login_required, Flask-
Login's own unauthorized() redirects to /login?next=<that POST-only URL>
(Flask-Login builds this from request.url — not our code, its own
default). The hypothesis: after Google sign-in, the app redirects to that
`next` with a GET, which 405s.

Reproducing "session expired" precisely: we log in for real (to render a
genuine csrf_token into a page, exactly as a real browser would have one
sitting in an already-loaded form), then drop just `_user_id` from the
session while leaving the rest (critically, csrf_token) intact — this is
what "logged out survives your csrf token" actually looks like server-side,
as distinct from a wiped/expired session cookie (which would fail CSRF too
and never reach Flask-Login's redirect at all).

EMPIRICAL FINDING on the code as it stood before this test: the
hypothesis's exact failure mode (a 405 after login) does NOT reproduce —
because `_complete_login` in app/auth.py never reads `next` at all, in
either direction. It unconditionally redirects to the dashboard. That
avoids a 405 by accident, not by design: it also means a legitimate safe
`next` (e.g. /goals, from a POST to /goals that also has a GET at the same
path) gets silently thrown away, landing the user somewhere they didn't
intend. test_next_is_dropped_even_when_it_was_perfectly_safe below pins
that gap — it fails before the fix (current code always lands on /) and
passes after (lands back on the safe `next`).

FIX: /login now stores a validated `next` (via the same _safe_relative_path
used for the facts/confirm-stale redirects) in the session; _complete_login
reads and clears it, using it only if still valid at that point, falling
back to the dashboard otherwise — covering BOTH directions: using next
when it's safe, and never using it when it isn't (that part already
couldn't be reproduced as a live failure, but is now tested explicitly so
it can never regress either).
"""
import re

from flask import redirect as flask_redirect

from app import auth
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _get_a_real_csrf_token_then_expire_login_only(client, user_id):
    """Logs in for real (so a genuine csrf_token gets generated and
    embedded in a rendered page, same as a real browser would have), then
    removes only `_user_id` — simulating a login that's expired while the
    underlying session (and its csrf_token) is still intact."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    page = client.get("/")
    token = TOKEN_RE.search(page.data.decode()).group(1)
    with client.session_transaction() as sess:
        sess.pop("_user_id", None)
    return token


def _stub_oauth(email, google_sub):
    """No real network call to Google anywhere — authorize_redirect,
    authorize_access_token, and parse_id_token are all stubbed, same
    spirit as _complete_login's own "split out so tests can exercise this
    without a real OAuth handshake" (test_auth_allowlist.py)."""
    auth.oauth.google.authorize_redirect = lambda *a, **k: flask_redirect("https://accounts.google.com/fake")
    auth.oauth.google.authorize_access_token = lambda *a, **k: {"fake": "token"}
    auth.oauth.google.parse_id_token = lambda *a, **k: {"email": email, "sub": google_sub}


def _complete_real_login_round_trip(client, login_redirect_location):
    """Follows /login?next=... (stubbed, no network) then /auth/callback
    (also stubbed) through the REAL routes, on the SAME client session —
    this is "complete the login callback with the existing test fake"
    wired through the actual HTTP flow, not a bypassed test_request_context,
    so session continuity (where `next` must survive to) is real."""
    login_resp = client.get(login_redirect_location)
    assert login_resp.status_code == 302  # to the stubbed "Google" URL
    return client.get("/auth/callback")


def test_crafted_fact_confirm_next_does_not_405_after_login(client, pg_conn, owner_user_id):
    """The literal reported shape: expired login hitting a fact's /confirm,
    then signing back in. Whatever the mechanism, the end state must never
    be a 405."""
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.bonus_expected", 2000, Unit.GBP, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    token = _get_a_real_csrf_token_then_expire_login_only(client, owner_user_id)

    resp = client.post(
        "/facts/income.shannon.bonus_expected/confirm", data={"csrf_token": token},
    )
    assert resp.status_code == 302
    login_location = resp.headers["Location"]
    assert login_location.startswith("/login?next=")

    _stub_oauth("shannon@example.com", "google-sub-owner")
    callback_resp = _complete_real_login_round_trip(client, login_location)
    assert callback_resp.status_code == 302
    final_location = callback_resp.headers["Location"]
    assert final_location != "/facts/income.shannon.bonus_expected/confirm"

    final_page = client.get(final_location)
    assert final_page.status_code == 200


def test_crafted_tasks_toggle_next_does_not_405_after_login(client, pg_conn, owner_user_id):
    token = _get_a_real_csrf_token_then_expire_login_only(client, owner_user_id)

    resp = client.post("/tasks/1/toggle", data={"csrf_token": token})
    assert resp.status_code == 302
    login_location = resp.headers["Location"]
    assert "next=%2Ftasks%2F1%2Ftoggle" in login_location

    _stub_oauth("shannon@example.com", "google-sub-owner")
    callback_resp = _complete_real_login_round_trip(client, login_location)
    final_location = callback_resp.headers["Location"]
    assert final_location != "/tasks/1/toggle"

    final_page = client.get(final_location)
    assert final_page.status_code == 200


def test_crafted_goals_create_next_lands_safely_and_is_get_capable(client, pg_conn, owner_user_id):
    """/goals is POST (create) AND GET (list) at the identical path — the
    `next` Flask-Login builds here (request.url for the POST) happens to
    already be GET-capable, so landing back on it after login is fine and
    actually the more helpful outcome (not forced back to the dashboard
    for no reason)."""
    token = _get_a_real_csrf_token_then_expire_login_only(client, owner_user_id)

    resp = client.post("/goals", data={"csrf_token": token})
    assert resp.status_code == 302
    login_location = resp.headers["Location"]
    assert "next=%2Fgoals" in login_location

    _stub_oauth("shannon@example.com", "google-sub-owner")
    callback_resp = _complete_real_login_round_trip(client, login_location)
    final_location = callback_resp.headers["Location"]

    final_page = client.get(final_location)
    assert final_page.status_code == 200


def test_next_is_used_when_it_was_perfectly_safe_not_silently_dropped(client, pg_conn, owner_user_id):
    """Pins the real gap: before the fix, `_complete_login` ignored `next`
    unconditionally, even when it was entirely safe (e.g. plain /goals) —
    landing the user somewhere they didn't ask for, every single time."""
    token = _get_a_real_csrf_token_then_expire_login_only(client, owner_user_id)

    resp = client.post("/goals", data={"csrf_token": token})
    login_location = resp.headers["Location"]

    _stub_oauth("shannon@example.com", "google-sub-owner")
    callback_resp = _complete_real_login_round_trip(client, login_location)
    assert callback_resp.headers["Location"] == "/goals"


def test_next_falls_back_to_dashboard_when_unsafe(client, pg_conn, owner_user_id):
    token = _get_a_real_csrf_token_then_expire_login_only(client, owner_user_id)

    resp = client.post("/tasks/1/toggle", data={"csrf_token": token})
    login_location = resp.headers["Location"]

    _stub_oauth("shannon@example.com", "google-sub-owner")
    callback_resp = _complete_real_login_round_trip(client, login_location)
    assert callback_resp.headers["Location"] == "/"


def test_login_consumes_next_via_the_shared_get_capable_validator(app):
    """Checks the actual mechanism, not just the outcome: /login must
    validate `next` with the same validator the facts/goals redirects use
    (app.routes._safe_relative_path, backed by _get_allowed), not a
    bespoke or absent check."""
    import inspect

    source = inspect.getsource(auth)
    assert "_safe_relative_path" in source, (
        "expected auth.py to reuse app.routes._safe_relative_path (the "
        "GET-capability-checking validator), not reimplement its own"
    )


# ── Friendlier login-required message (covers expired AND never-logged-in) ─

def test_login_manager_message_does_not_assume_a_prior_session(app):
    assert app.login_manager.login_message == "Please sign in to continue."
    assert app.login_manager.login_message_category == "error"


def test_login_required_flash_renders_on_the_page_after_signing_back_in(client, pg_conn, owner_user_id):
    """End to end: the flash Flask-Login sets when it bounces an
    unauthenticated request to /login actually survives the whole round
    trip and renders, in our existing flash styling, on the page the user
    lands on once they've signed in."""
    token = _get_a_real_csrf_token_then_expire_login_only(client, owner_user_id)

    resp = client.post("/goals", data={"csrf_token": token})
    login_location = resp.headers["Location"]

    _stub_oauth("shannon@example.com", "google-sub-owner")
    callback_resp = _complete_real_login_round_trip(client, login_location)
    final_page = client.get(callback_resp.headers["Location"])

    body = final_page.data.decode()
    assert "Please sign in to continue." in body
    assert 'class="flash error"' in body
