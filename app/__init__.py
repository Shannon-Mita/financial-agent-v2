from . import vendor_path  # noqa: F401  (must run before any facts_layer/tax_engine import)

from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect

from . import auth, db, routes
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

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def _load_user(user_id):
        return load_user_by_id(db.get_conn(), user_id)

    csrf.init_app(app)
    auth.init_app(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(routes.bp)

    return app
