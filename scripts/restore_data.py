#!/usr/bin/env python3
"""
Restores a scripts/export_data.py JSON export into a database. Refuses
outright if the TARGET database already has a single row anywhere in any
of the six tables — this is a from-empty restore only (setting up a fresh
environment, or recovering after data loss onto a brand-new database), not
a merge or an overwrite. See docs/RUNBOOK.md for when and how to use this.

Reads DATABASE_URL from the environment — never prints it or any other env
var. The whole restore is one transaction: any error rolls back everything,
never leaving a half-restored database.

A successful run prints a row count per table and exits 0:
    Restored users: 2 rows
    Restored facts: 47 rows
    Restored goals: 3 rows
    Restored goal_assignees: 2 rows
    Restored tasks: 5 rows
    Restored audit_log: 11 rows
"""
import json
import os
import sys

import psycopg2
import psycopg2.extras

from scripts.export_data import TABLES

# Columns whose exported Python dict value needs psycopg2's explicit JSONB
# adapter — passing a raw dict as a parameter does NOT auto-adapt to jsonb.
JSON_COLUMNS = {"audit_log": {"snapshot"}}


class NotEmptyError(RuntimeError):
    pass


def refuse_unless_empty(conn) -> None:
    non_empty = []
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"SELECT count(*) FROM {table}")
            if cur.fetchone()[0] > 0:
                non_empty.append(table)
    if non_empty:
        raise NotEmptyError(
            "Refusing to restore: not empty — "
            + ", ".join(f"{t} has rows" for t in non_empty)
        )


def restore_all(conn, data: dict) -> dict:
    refuse_unless_empty(conn)

    counts = {}
    with conn.cursor() as cur:
        for table, columns in TABLES.items():
            rows = data.get(table, [])
            json_cols = JSON_COLUMNS.get(table, set())
            placeholders = ", ".join(f"%({c})s" for c in columns)
            sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            for row in rows:
                params = dict(row)
                for jc in json_cols:
                    params[jc] = psycopg2.extras.Json(params[jc])
                cur.execute(sql, params)
            counts[table] = len(rows)

            if "id" in columns:
                cur.execute(
                    f"SELECT setval('{table}_id_seq', "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                    f"(SELECT MAX(id) FROM {table}) IS NOT NULL)"
                )
    conn.commit()
    return counts


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    if len(sys.argv) != 2:
        sys.exit("Usage: restore_data.py <export-file.json>")
    export_path = sys.argv[1]
    if not os.path.exists(export_path):
        sys.exit(f"No such file: {export_path}")

    with open(export_path) as f:
        data = json.load(f)

    conn = psycopg2.connect(database_url)
    try:
        counts = restore_all(conn, data)
    except Exception as exc:
        conn.rollback()
        sys.exit(str(exc))

    for table, n in counts.items():
        print(f"Restored {table}: {n} rows")


if __name__ == "__main__":
    main()
