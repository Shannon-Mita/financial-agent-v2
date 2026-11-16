"""
Postgres-backed store for strategy_notes (migrations/005_strategy_notes.sql).
Append-only — no update_note/delete_note: the DB trigger blocks those
statements outright, same idiom as app/decision_log_store.py. Every
creation also writes a shared audit_log row.
"""
from __future__ import annotations

from datetime import date, datetime

import psycopg2.extras

NOTE_COLUMNS = (
    "id", "strategy_id", "step_id", "body", "link",
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
            VALUES ('strategy_note', %s, 'created', %s, %s)
            """,
            (entity_id, psycopg2.extras.Json({k: _jsonable(v) for k, v in snapshot.items()}), user_id),
        )


def list_notes_for_strategy(conn, strategy_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(NOTE_COLUMNS)} FROM strategy_notes "
            "WHERE strategy_id = %s ORDER BY created_at DESC, id DESC",
            (strategy_id,),
        )
        return [_row_to_dict(r, NOTE_COLUMNS) for r in cur.fetchall()]


def create_note(conn, *, strategy_id, step_id, body, link, user_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO strategy_notes (strategy_id, step_id, body, link, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, strategy_id, step_id, body, link, created_at, created_by_user_id
            """,
            (strategy_id, step_id, body, link, user_id),
        )
        note = _row_to_dict(cur.fetchone(), NOTE_COLUMNS)
    _log(conn, note["id"], note, user_id)
    conn.commit()
    return note["id"]


def strategy_has_notes(conn, strategy_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM strategy_notes WHERE strategy_id = %s LIMIT 1", (strategy_id,))
        return cur.fetchone() is not None


def step_has_notes(conn, step_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM strategy_notes WHERE step_id = %s LIMIT 1", (step_id,))
        return cur.fetchone() is not None
