#!/usr/bin/env python3
"""
Manual export: dumps the current Postgres contents (every table in the
schema — users, the full facts history, and Stage 1's goals/goal_assignees/
tasks/audit_log) to a timestamped JSON file under ./exports/, so Shannon
always has a way to pull the household's data out of the host without
relying on the host's own backup tooling. See docs/RUNBOOK.md for when to
run this and how to restore from the result (scripts/restore_data.py).

Reads DATABASE_URL from the environment — never prints it or any other env
var, only the data rows themselves.

A successful run prints the output path and a row count for each table, e.g.:
    Wrote exports/financial-agent-v2-export-<timestamp>.json
    users: 2 rows
    facts: 47 rows
    goals: 3 rows
    goal_assignees: 2 rows
    tasks: 5 rows
    audit_log: 11 rows
and exits 0.
"""
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2

# Every table in migrations/001_init.sql + 002_goals.sql, in an order that's
# safe to restore in (parents before the rows that reference them) — see
# scripts/restore_data.py. Columns are listed explicitly (not `SELECT *`) so
# the export's shape is stable even if a column is ever reordered.
TABLES = {
    "users": ("id", "google_sub", "email", "role", "created_at"),
    "facts": (
        "id", "key", "value_text", "value_type", "unit", "source", "category",
        "owner", "as_of", "entered_at", "note", "entered_by_user_id",
    ),
    "goals": (
        "id", "title", "type", "target_value", "target_date", "source_fact_key",
        "target_date_fact_key", "progress_fact_keys", "cadence_period",
        "cadence_amount", "status", "parent_id", "created_at",
        "created_by_user_id", "updated_at", "updated_by_user_id",
    ),
    "goal_assignees": ("goal_id", "user_id"),
    "tasks": (
        "id", "goal_id", "title", "assignee_user_id", "done", "done_at",
        "done_by_user_id", "created_at", "created_by_user_id",
    ),
    "audit_log": (
        "id", "entity_type", "entity_id", "event_type", "snapshot",
        "changed_by_user_id", "changed_at",
    ),
}

# Row order within each table — "id" everywhere there is one; goal_assignees
# has no single-column primary key, so order by its composite key instead.
ORDER_BY = {"goal_assignees": "goal_id, user_id"}


def export_all(conn) -> dict:
    data = {}
    with conn.cursor() as cur:
        for table, columns in TABLES.items():
            order_by = ORDER_BY.get(table, "id")
            cur.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order_by}")
            data[table] = [dict(zip(columns, row)) for row in cur.fetchall()]
    return data


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    conn = psycopg2.connect(database_url)
    data = export_all(conn)

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
