"""
Google sign-in via Authlib (a maintained OAuth2 client library — this is
"auth handled by a reputable library," not a hand-rolled OAuth flow). Only
emails in Config.email_role_map() are allowed a session; anyone else is
rejected before any user row or session is created.
"""
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, current_app, redirect, request, session, url_for
from flask_login import login_required, login_user, logout_user

from .db import get_conn
from .users import resolve_role_for_email, upsert_user

bp = Blueprint("auth", __name__)
oauth = OAuth()

POST_LOGIN_NEXT_SESSION_KEY = "post_login_next"


def init_app(app):
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@bp.route("/login")
def login():
    # Flask-Login's own unauthorized() handler built this `next` from
    # request.url of whatever POST (or GET) triggered the redirect here —
    # it has no idea whether that URL even accepts GET. Validate it the
    # same way the facts/goals redirects do (same-site AND GET-capable)
    # before trusting it, and stash the validated result (or None) in the
    # session — it has to survive the round trip to Google and back,
    # which drops query strings, so the OAuth redirect_uri can't carry it.
    from .routes import _safe_relative_path

    session[POST_LOGIN_NEXT_SESSION_KEY] = _safe_relative_path(request.args.get("next"))
    redirect_uri = url_for("auth.callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route("/auth/callback")
def callback():
    token = oauth.google.authorize_access_token()
    claims = oauth.google.parse_id_token(token, nonce=session.get("nonce"))
    return _complete_login(claims["email"], claims["sub"])


def _complete_login(email: str, google_sub: str):
    """Split out so tests can exercise the allowlist decision without going
    through a real Google OAuth handshake."""
    role = resolve_role_for_email(email, current_app.config["EMAIL_ROLE_MAP"])
    if role is None:
        abort(403, description="This Google account is not authorised for this app.")
    user = upsert_user(get_conn(), google_sub, email, role)
    session.permanent = True  # 30-day lifetime (PERMANENT_SESSION_LIFETIME), refreshed on every request
    login_user(user)

    # Re-validate even though /login already did — the route that sets
    # this session key is the one entry point into this value, but
    # re-checking here costs nothing and means this function is correct
    # on its own, not just correct given what /login happens to do first.
    from .routes import _safe_relative_path

    next_target = _safe_relative_path(session.pop(POST_LOGIN_NEXT_SESSION_KEY, None))
    return redirect(next_target or url_for("routes.dashboard"))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
