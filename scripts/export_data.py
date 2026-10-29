#!/usr/bin/env python3
"""
Manual export: dumps the current Postgres contents (users + full facts
history) to a timestamped JSON file under ./exports/, so Shannon always has
a way to pull the household's data out of the host without relying on the
host's own backup tooling.

Reads DATABASE_URL from the environment — never prints it or any other env
var, only the data rows themselves.

A successful run prints the output path and a row count for each table, e.g.:
    Wrote exports/financial-agent-v2-export-<timestamp>.json
    users: 2 rows
    facts: 47 rows
and exits 0.
"""
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    conn = psycopg2.connect(database_url)
    data = {}

    with conn.cursor() as cur:
        cur.execute("SELECT id, email, role, created_at FROM users ORDER BY id")
        cols = [c.name for c in cur.description]
        data["users"] = [dict(zip(cols, row)) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT id, key, value_text, value_type, unit, source, category,
                   owner, as_of, entered_at, note, entered_by_user_id
            FROM facts ORDER BY id
            """
        )
        cols = [c.name for c in cur.description]
        data["facts"] = [dict(zip(cols, row)) for row in cur.fetchall()]

    out_dir = os.path.join(os.path.dirname(__file__), "..", "exports")
    os.makedirs(out_dir, exist_ok=True)
    stamp = os.environ.get("EXPORT_TIMESTAMP")  # tests can pin this
    if not stamp:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(out_dir, f"financial-agent-v2-export-{stamp}.json")

    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Wrote {out_path}")
    for table, rows in data.items():
        print(f"{table}: {len(rows)} rows")


if __name__ == "__main__":
    main()
