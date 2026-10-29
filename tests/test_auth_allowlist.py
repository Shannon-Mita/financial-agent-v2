"""
Email allowlist enforcement (Shannon's amendment #1). The rejection path
never touches the database, so it runs with no Postgres available; the two
success paths need a real one (they write a users row) and skip without
TEST_DATABASE_URL.

No real network call to Google happens anywhere here — we call the
post-OAuth completion step directly with a fake (email, google_sub) pair,
never going near accounts.google.com.
"""
import pytest
from flask_login import current_user
from werkzeug.exceptions import Forbidden

from app import auth


def test_unauthorised_email_is_rejected(app):
    with app.test_request_context():
        with pytest.raises(Forbidden):
            auth._complete_login("random-stranger@example.com", "sub-stranger")


def test_owner_email_is_allowed(app, pg_conn):
    with app.test_request_context():
        resp = auth._complete_login("shannon@example.com", "sub-shannon")
        assert resp.status_code == 302
        assert current_user.is_authenticated
        assert current_user.role == "owner"


def test_partner_email_is_allowed(app, pg_conn):
    with app.test_request_context():
        resp = auth._complete_login("partner@example.com", "sub-partner")
        assert resp.status_code == 302
        assert current_user.is_authenticated
        assert current_user.role == "member"


def test_case_and_whitespace_insensitive_allowlist_match(app):
    with app.test_request_context():
        with pytest.raises(Forbidden):
            # Not an allowlisted address regardless of casing — this just
            # proves rejection isn't accidentally case-sensitive-bypassable
            # in the OTHER direction (an unlisted address stays rejected).
            auth._complete_login("  RANDOM-STRANGER@EXAMPLE.COM  ", "sub-stranger-2")
