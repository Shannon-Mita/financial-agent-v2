"""
Postgres-backed store for goals, tasks, and the shared audit_log — Stage 1
(migrations/002_goals.sql). Plain SQL, parameterised, no ORM, matching
app/store.py's own style. Unlike facts, goals/tasks are mutable rows; every
mutation also writes an audit_log row (append-only, DB-enforced) so there's
a full history trail independent of the mutable row's current state.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import psycopg2.extras

GOAL_COLUMNS = (
    "id", "title", "type", "target_value", "target_date",
    "source_fact_key", "target_date_fact_key", "progress_fact_keys",
    "cadence_period", "cadence_amount", "status", "parent_id",
    "created_at", "created_by_user_id", "updated_at", "updated_by_user_id",
)

TASK_COLUMNS = (
    "id", "goal_id", "title", "assignee_user_id", "done", "done_at",
    "done_by_user_id", "created_at", "created_by_user_id",
)


def _row_to_dict(row, columns):
    return dict(zip(columns, row))


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _snapshot(d: dict) -> dict:
    return {k: _jsonable(v) for k, v in d.items()}


def _log(conn, entity_type, entity_id, event_type, snapshot, user_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, event_type, snapshot, changed_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (entity_type, entity_id, event_type, psycopg2.extras.Json(_snapshot(snapshot)), user_id),
        )


# ── Goals ────────────────────────────────────────────────────────────────

def list_goals(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(GOAL_COLUMNS)} FROM goals ORDER BY id")
        goals = [_row_to_dict(r, GOAL_COLUMNS) for r in cur.fetchall()]
        cur.execute("SELECT goal_id, user_id FROM goal_assignees ORDER BY goal_id")
        assignees = cur.fetchall()
    by_goal: dict[int, list[int]] = {}
    for goal_id, user_id in assignees:
        by_goal.setdefault(goal_id, []).append(user_id)
    for g in goals:
        g["assignee_user_ids"] = by_goal.get(g["id"], [])
    return goals


def get_goal(conn, goal_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(GOAL_COLUMNS)} FROM goals WHERE id = %s", (goal_id,))
        row = cur.fetchone()
        if row is None:
            return None
        goal = _row_to_dict(row, GOAL_COLUMNS)
        cur.execute("SELECT user_id FROM goal_assignees WHERE goal_id = %s ORDER BY user_id", (goal_id,))
        goal["assignee_user_ids"] = [r[0] for r in cur.fetchall()]
    return goal


def has_children(conn, goal_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM goals WHERE parent_id = %s LIMIT 1", (goal_id,))
        return cur.fetchone() is not None


def create_goal(conn, *, title, type, target_value, target_date,
                 source_fact_key, target_date_fact_key, progress_fact_keys,
                 cadence_period, cadence_amount, parent_id,
                 assignee_user_ids, user_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO goals
              (title, type, target_value, target_date, source_fact_key,
               target_date_fact_key, progress_fact_keys, cadence_period,
               cadence_amount, parent_id, created_by_user_id, updated_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, type, target_value, target_date, source_fact_key,
             target_date_fact_key, progress_fact_keys, cadence_period,
             cadence_amount, parent_id, user_id, user_id),
        )
        goal_id = cur.fetchone()[0]
        for uid in assignee_user_ids or []:
            cur.execute(
                "INSERT INTO goal_assignees (goal_id, user_id) VALUES (%s, %s)",
                (goal_id, uid),
            )
    goal = get_goal(conn, goal_id)
    _log(conn, "goal", goal_id, "created", goal, user_id)
    conn.commit()
    return goal_id


def update_goal(conn, goal_id: int, fields: dict, *, assignee_user_ids, user_id) -> None:
    """`fields` is the full set of editable columns (title/type/target_value/
    target_date/source_fact_key/target_date_fact_key/progress_fact_keys/
    cadence_period/cadence_amount/parent_id) — the goal edit form always
    submits all of them, so a partial-update footgun isn't possible here."""
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE goals SET {set_clause}, updated_at = now(), updated_by_user_id = %s
            WHERE id = %s
            """,
            (*fields.values(), user_id, goal_id),
        )
        cur.execute("DELETE FROM goal_assignees WHERE goal_id = %s", (goal_id,))
        for uid in assignee_user_ids or []:
            cur.execute(
                "INSERT INTO goal_assignees (goal_id, user_id) VALUES (%s, %s)",
                (goal_id, uid),
            )
    goal = get_goal(conn, goal_id)
    _log(conn, "goal", goal_id, "updated", goal, user_id)
    conn.commit()


def set_goal_status(conn, goal_id: int, status: str, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE goals SET status = %s, updated_at = now(), updated_by_user_id = %s WHERE id = %s",
            (status, user_id, goal_id),
        )
    _log(conn, "goal", goal_id, "status_changed", {"status": status}, user_id)
    conn.commit()


def delete_goal(conn, goal_id: int, user_id: int) -> None:
    goal = get_goal(conn, goal_id)
    _log(conn, "goal", goal_id, "deleted", goal, user_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM goals WHERE id = %s", (goal_id,))
    conn.commit()


# ── Tasks ────────────────────────────────────────────────────────────────

def list_tasks(conn, goal_id: int | None = None) -> list[dict]:
    with conn.cursor() as cur:
        if goal_id is None:
            cur.execute(f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks ORDER BY id")
        else:
            cur.execute(
                f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE goal_id = %s ORDER BY id",
                (goal_id,),
            )
        return [_row_to_dict(r, TASK_COLUMNS) for r in cur.fetchall()]


def get_task(conn, task_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = %s", (task_id,))
        row = cur.fetchone()
    return _row_to_dict(row, TASK_COLUMNS) if row else None


def create_task(conn, *, title, goal_id, assignee_user_id, user_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (title, goal_id, assignee_user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (title, goal_id, assignee_user_id, user_id),
        )
        task_id = cur.fetchone()[0]
    task = get_task(conn, task_id)
    _log(conn, "task", task_id, "created", task, user_id)
    conn.commit()
    return task_id


def update_task(conn, task_id: int, *, title, assignee_user_id, user_id) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tasks SET title = %s, assignee_user_id = %s WHERE id = %s",
            (title, assignee_user_id, task_id),
        )
    task = get_task(conn, task_id)
    _log(conn, "task", task_id, "updated", task, user_id)
    conn.commit()


def delete_task(conn, task_id: int, user_id: int) -> None:
    task = get_task(conn, task_id)
    _log(conn, "task", task_id, "deleted", task, user_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()


def toggle_task(conn, task_id: int, done: bool, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tasks SET done = %s,
                              done_at = CASE WHEN %s THEN now() ELSE NULL END,
                              done_by_user_id = CASE WHEN %s THEN %s ELSE NULL END
            WHERE id = %s
            """,
            (done, done, done, user_id, task_id),
        )
    _log(conn, "task", task_id, "task_done" if done else "task_undone", {"done": done}, user_id)
    conn.commit()


# ── Users (for assignee pickers / display names) ────────────────────────

def list_users(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, role FROM users ORDER BY id")
        return [{"id": r[0], "email": r[1], "role": r[2]} for r in cur.fetchall()]
