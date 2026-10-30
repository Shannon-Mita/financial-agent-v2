from . import vendor_path  # noqa: F401  (must run before any facts_layer/tax_engine import)

from datetime import timedelta

from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect

from . import auth, db, pwa, routes, security_headers
from .config import Config
from .users import load_user_by_id

login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    cfg = config or Config()

    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["DATABASE_URL"] = cfg.DATABASE_URL
    app.config["GOOGLE_CLIENT_ID"] = cfg.GOOGLE_CLIENT_ID
    app.config["GOOGLE_CLIENT_SECRET"] = cfg.GOOGLE_CLIENT_SECRET
    app.config["EMAIL_ROLE_MAP"] = cfg.email_role_map()

    # Session cookie hardening (Shannon's amendment #3).
    app.config["SESSION_COOKIE_SECURE"] = cfg.SESSION_COOKIE_SECURE
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Sessions are marked permanent at login (see auth._complete_login) and
    # last 30 days — long enough neither of you gets nagged to re-login
    # constantly on a household app, short enough a lost/sold phone isn't
    # exposed forever. SESSION_REFRESH_EACH_REQUEST defaults to True (not
    # overridden here), so every request slides the expiry forward again —
    # 30 days of INACTIVITY signs you out, not 30 days from first login.
    # Changing SECRET_KEY invalidates every existing session immediately
    # (see docs/RUNBOOK.md).
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    # Flask-Login's own default ("Please log in to access this page.") is
    # shown whenever @login_required bounces a request with no valid
    # session — in practice for this app, almost always an expired login
    # rather than a first-ever visit. Friendlier wording, and "error" so it
    # renders with the same styling our own flash messages already use.
    login_manager.login_message = "Your session expired — please sign in again."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def _load_user(user_id):
        return load_user_by_id(db.get_conn(), user_id)

    csrf.init_app(app)
    auth.init_app(app)
    security_headers.init_app(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(pwa.bp)
    app.register_blueprint(routes.bp)

    return app
