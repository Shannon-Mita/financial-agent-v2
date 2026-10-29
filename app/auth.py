"""
Google sign-in via Authlib (a maintained OAuth2 client library — this is
"auth handled by a reputable library," not a hand-rolled OAuth flow). Only
emails in Config.email_role_map() are allowed a session; anyone else is
rejected before any user row or session is created.
"""
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, current_app, redirect, session, url_for
from flask_login import login_required, login_user, logout_user

from .db import get_conn
from .users import resolve_role_for_email, upsert_user

bp = Blueprint("auth", __name__)
oauth = OAuth()


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
    login_user(user)
    return redirect(url_for("routes.dashboard"))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
