"""
Session lifetime: permanent sessions, 30 days, refreshing on each request
(Flask's own SESSION_REFRESH_EACH_REQUEST default, left untouched).
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from flask import session

from app import auth


def test_permanent_session_lifetime_is_30_days(app):
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=30)


def test_session_refresh_each_request_not_disabled(app):
    """Flask's default (True) is what makes a permanent session's expiry
    slide forward on every request — "refreshes on use". We rely on the
    default rather than setting it explicitly, so this pins that nothing
    has turned it off."""
    assert app.config.get("SESSION_REFRESH_EACH_REQUEST", True) is True


def test_login_marks_the_session_permanent(app, pg_conn):
    with app.test_request_context():
        auth._complete_login("shannon@example.com", "sub-shannon-permanent")
        assert session.permanent is True


def test_cookie_carries_a_30_day_max_age_once_permanent(client, pg_conn, owner_user_id):
    """End-to-end: with session.permanent=True and our configured
    PERMANENT_SESSION_LIFETIME, the actual Set-Cookie header Flask emits
    must reflect a ~30-day lifetime, not a browser-session-only cookie."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner_user_id)
        sess.permanent = True

    resp = client.get("/")
    set_cookie = resp.headers.get("Set-Cookie", "")
    assert "Max-Age=" in set_cookie or "Expires=" in set_cookie

    if "Max-Age=" in set_cookie:
        max_age = int(set_cookie.split("Max-Age=")[1].split(";")[0])
        delta = timedelta(seconds=max_age)
    else:
        expires_raw = set_cookie.split("Expires=")[1].split(";")[0]
        expires = parsedate_to_datetime(expires_raw)
        delta = expires - datetime.now(timezone.utc)

    thirty_days = timedelta(days=30)
    assert abs(delta - thirty_days) < timedelta(minutes=5)  # allow a little clock slack
