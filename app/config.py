"""
Config from environment variables only. Never read .env contents into logs
or error messages — if a required variable is missing, name the variable,
not its value.
"""
import os


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


class Config:
    def __init__(self):
        self.SECRET_KEY = _required("SECRET_KEY")
        self.DATABASE_URL = _required("DATABASE_URL")

        self.OWNER_EMAIL = _required("OWNER_EMAIL").strip().lower()
        self.PARTNER_EMAIL = _required("PARTNER_EMAIL").strip().lower()

        self.GOOGLE_CLIENT_ID = _required("GOOGLE_CLIENT_ID")
        self.GOOGLE_CLIENT_SECRET = _required("GOOGLE_CLIENT_SECRET")

        # Only ever False for local HTTP dev — Render serves HTTPS, so this
        # should stay True everywhere except FLASK_DEBUG-style local runs.
        self.SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() != "false"

    def email_role_map(self) -> dict:
        return {self.OWNER_EMAIL: "owner", self.PARTNER_EMAIL: "member"}
