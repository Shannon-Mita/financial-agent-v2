"""
Postgres-backed store for strategies, their goal/milestone links, levers,
and steps (migrations/003_strategies.sql). Plain parameterised SQL, no
ORM, matching app/goals_store.py's own style. No audit_log here — Stage 2
§5's data model tracks who/when on the strategies row itself
(created/updated_at/by_user_id); an append-only audit trail wasn't part of
what was asked for strategies.
"""
from __future__ import annotations

STRATEGY_COLUMNS = (
    "id", "title", "detail", "area", "status", "work_lives_in",
    "effect_on_net_worth", "effect_on_passive_income", "risks_childcare_eligibility",
    "from_when", "archived_reason", "archived_date", "last_reviewed_date", "source",
    "created_at", "created_by_user_id", "updated_at", "updated_by_user_id",
)

LEVER_COLUMNS = ("id", "strategy_id", "dimension", "delta", "from_date")

STEP_COLUMNS = (
    "id", "strategy_id", "title", "assignee_user_id", "done", "done_at",
    "done_by_user_id", "created_at", "created_by_user_id",
)


def _row_to_dict(row, columns):
    return dict(zip(columns, row))


# ── Strategies ───────────────────────────────────────────────────────────

def list_strategies(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(STRATEGY_COLUMNS)} FROM strategies ORDER BY id")
        return [_row_to_dict(r, STRATEGY_COLUMNS) for r in cur.fetchall()]


def get_strategy(conn, strategy_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(STRATEGY_COLUMNS)} FROM strategies WHERE id = %s", (strategy_id,))
        row = cur.fetchone()
    return _row_to_dict(row, STRATEGY_COLUMNS) if row else None


def create_strategy(conn, *, title, detail, area, status, work_lives_in, source,
                     effect_on_net_worth, effect_on_passive_income,
                     risks_childcare_eligibility, from_when, user_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO strategies
              (title, detail, area, status, work_lives_in, source,
               effect_on_net_worth, effect_on_passive_income,
               risks_childcare_eligibility, from_when,
               created_by_user_id, updated_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, detail, area, status, work_lives_in, source,
             effect_on_net_worth, effect_on_passive_income,
             risks_childcare_eligibility, from_when, user_id, user_id),
        )
        strategy_id = cur.fetchone()[0]
    conn.commit()
    return strategy_id


def update_strategy(conn, strategy_id: int, fields: dict, *, user_id: int) -> None:
    """`fields` is the full set of editable columns the strategy edit form
    submits (title/detail/status/work_lives_in/effect_on_net_worth/
    effect_on_passive_income/risks_childcare_eligibility/from_when/
    last_reviewed_date) — never archived_reason/archived_date, which only
    archive_strategy() may set."""
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE strategies SET {set_clause}, updated_at = now(), updated_by_user_id = %s WHERE id = %s",
            (*fields.values(), user_id, strategy_id),
        )
    conn.commit()


def archive_strategy(conn, strategy_id: int, *, reason: str, archived_date, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE strategies
            SET status = 'archived', archived_reason = %s, archived_date = %s,
                updated_at = now(), updated_by_user_id = %s
            WHERE id = %s
            """,
            (reason, archived_date, user_id, strategy_id),
        )
    conn.commit()


def delete_strategy(conn, strategy_id: int, *, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
    conn.commit()


# ── Goal/milestone links ─────────────────────────────────────────────────

def list_strategy_goal_ids(conn, strategy_id: int) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT goal_id FROM strategy_goal_links WHERE strategy_id = %s ORDER BY goal_id", (strategy_id,)
        )
        return [r[0] for r in cur.fetchall()]


def set_strategy_goal_links(conn, strategy_id: int, goal_ids: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM strategy_goal_links WHERE strategy_id = %s", (strategy_id,))
        for goal_id in goal_ids or []:
            cur.execute(
                "INSERT INTO strategy_goal_links (strategy_id, goal_id) VALUES (%s, %s)",
                (strategy_id, goal_id),
            )
    conn.commit()


# ── Levers ───────────────────────────────────────────────────────────────

def list_strategy_levers(conn, strategy_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(LEVER_COLUMNS)} FROM strategy_levers WHERE strategy_id = %s ORDER BY id",
            (strategy_id,),
        )
        return [_row_to_dict(r, LEVER_COLUMNS) for r in cur.fetchall()]


def set_strategy_levers(conn, strategy_id: int, levers: list[dict]) -> None:
    """Replace-all, same pattern as goal_assignees — the strategy edit form
    always submits the full set of levers, never a partial update."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM strategy_levers WHERE strategy_id = %s", (strategy_id,))
        for lever in levers or []:
            cur.execute(
                "INSERT INTO strategy_levers (strategy_id, dimension, delta, from_date) VALUES (%s, %s, %s, %s)",
                (strategy_id, lever["dimension"], lever["delta"], lever["from_date"]),
            )
    conn.commit()


# ── Steps (mirrors app/goals_store.py's task functions) ─────────────────

def list_strategy_steps(conn, strategy_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(STEP_COLUMNS)} FROM strategy_steps WHERE strategy_id = %s ORDER BY id",
            (strategy_id,),
        )
        return [_row_to_dict(r, STEP_COLUMNS) for r in cur.fetchall()]


def get_strategy_step(conn, step_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(STEP_COLUMNS)} FROM strategy_steps WHERE id = %s", (step_id,))
        row = cur.fetchone()
    return _row_to_dict(row, STEP_COLUMNS) if row else None


def create_strategy_step(conn, *, strategy_id, title, assignee_user_id, user_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO strategy_steps (strategy_id, title, assignee_user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (strategy_id, title, assignee_user_id, user_id),
        )
        step_id = cur.fetchone()[0]
    conn.commit()
    return step_id


def update_strategy_step(conn, step_id: int, *, title, assignee_user_id, user_id) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE strategy_steps SET title = %s, assignee_user_id = %s WHERE id = %s",
            (title, assignee_user_id, step_id),
        )
    conn.commit()


def delete_strategy_step(conn, step_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM strategy_steps WHERE id = %s", (step_id,))
    conn.commit()


def toggle_strategy_step(conn, step_id: int, done: bool, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE strategy_steps SET done = %s,
                                       done_at = CASE WHEN %s THEN now() ELSE NULL END,
                                       done_by_user_id = CASE WHEN %s THEN %s ELSE NULL END
            WHERE id = %s
            """,
            (done, done, done, user_id, step_id),
        )
    conn.commit()
