#!/usr/bin/env python3
"""
One-off: apply every migrations/*.sql file to the database at DATABASE_URL,
in filename order (001_, 002_, ...). No psql needed — uses psycopg2, already
in requirements.txt.

Safe to re-run: every statement in every migration file is idempotent
(CREATE TABLE IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF
EXISTS + CREATE).

A successful run prints "Applied migrations/<file>." per file and exits 0.
Never prints DATABASE_URL or any other env var.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import connect, run_migration  # noqa: E402

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    migration_paths = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    if not migration_paths:
        sys.exit(f"No .sql files found in {os.path.relpath(MIGRATIONS_DIR)}.")

    conn = connect(database_url)
    for path in migration_paths:
        run_migration(conn, path)
        print(f"Applied {os.path.relpath(path)}.")
    conn.close()


if __name__ == "__main__":
    main()
