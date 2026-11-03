"""
Postgres-backed store for the decision log (migrations/004_decision_log.sql).
Append-only: there is no update_decision/delete_decision function here,
matching the DB-level trigger that blocks those statements outright — there
is nothing to call. Every creation also writes a shared audit_log row,
mirroring app/goals_store.py's create_goal, so the household's full history
(goals, tasks, decisions) lives in one place.
"""
from __future__ import annotations

from datetime import date, datetime

import psycopg2.extras

DECISION_COLUMNS = (
    "id", "decision_date", "decision", "reason", "assumptions",
    "created_at", "created_by_user_id",
)


def _row_to_dict(row, columns):
    return dict(zip(columns, row))


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _log(conn, entity_id, snapshot, user_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id)
            VALUES ('decision_log', %s, 'created', %s, %s)
            """,
            (entity_id, psycopg2.extras.Json({k: _jsonable(v) for k, v in snapshot.items()}), user_id),
        )


def list_decisions(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(DECISION_COLUMNS)} FROM decision_log "
            "ORDER BY decision_date DESC, id DESC"
        )
        return [_row_to_dict(r, DECISION_COLUMNS) for r in cur.fetchall()]


def create_decision(conn, *, decision_date, decision, reason, assumptions, user_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO decision_log (decision_date, decision, reason, assumptions, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, decision_date, decision, reason, assumptions, created_at, created_by_user_id
            """,
            (decision_date, decision, reason, assumptions or "", user_id),
        )
        entry = _row_to_dict(cur.fetchone(), DECISION_COLUMNS)
    _log(conn, entry["id"], entry, user_id)
    conn.commit()
    return entry["id"]
