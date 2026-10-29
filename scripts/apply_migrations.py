#!/usr/bin/env python3
"""
One-off: apply migrations/001_init.sql to the database at DATABASE_URL.
No psql needed — uses psycopg2, already in requirements.txt.

Safe to re-run: every statement in 001_init.sql is idempotent (CREATE TABLE
IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS + CREATE).

A successful run prints "Applied migrations/001_init.sql." and exits 0.
Never prints DATABASE_URL or any other env var.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import connect, run_migration  # noqa: E402

MIGRATION_PATH = os.path.join(os.path.dirname(__file__), "..", "migrations", "001_init.sql")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    conn = connect(database_url)
    run_migration(conn, MIGRATION_PATH)
    conn.close()
    print(f"Applied {os.path.relpath(MIGRATION_PATH)}.")


if __name__ == "__main__":
    main()
