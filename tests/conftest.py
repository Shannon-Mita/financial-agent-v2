import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("OWNER_EMAIL", "shannon@example.com")
os.environ.setdefault("PARTNER_EMAIL", "partner@example.com")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("SESSION_COOKIE_SECURE", "true")
os.environ.setdefault(
    "DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql://unused/unused")
)

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import run_migration  # noqa: E402

MIGRATION_PATH = os.path.join(os.path.dirname(__file__), "..", "migrations", "001_init.sql")


@pytest.fixture
def app():
    flask_app = create_app(Config())
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def pg_conn():
    """A real Postgres connection, schema applied, tables truncated. Skips
    (doesn't fail) when no test database is configured — append-only and
    store-contract tests need a real Postgres, not a stand-in."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — skipping Postgres-backed tests")
    import psycopg2

    conn = psycopg2.connect(url)
    run_migration(conn, MIGRATION_PATH)
    with conn.cursor() as cur:
        # TRUNCATE bypasses row-level UPDATE/DELETE triggers entirely (it's not
        # a DELETE statement) — safe for test isolation without weakening the
        # append-only guarantee application code relies on.
        cur.execute("TRUNCATE facts, users RESTART IDENTITY CASCADE")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def owner_user_id(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (google_sub, email, role) VALUES (%s, %s, %s) RETURNING id",
            ("google-sub-owner", "shannon@example.com", "owner"),
        )
        user_id = cur.fetchone()[0]
    pg_conn.commit()
    return user_id


@pytest.fixture
def member_user_id(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (google_sub, email, role) VALUES (%s, %s, %s) RETURNING id",
            ("google-sub-partner", "partner@example.com", "member"),
        )
        user_id = cur.fetchone()[0]
    pg_conn.commit()
    return user_id
