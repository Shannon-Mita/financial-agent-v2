"""
Schema-level tests for migrations/003_strategies.sql — strategies,
strategy_goal_links, strategy_levers, strategy_steps, and the CHECK
constraints encoding Stage 2 Step 4's rules. Needs a real Postgres (skips
without TEST_DATABASE_URL), same as test_migrations_002.py.
"""
import psycopg2
import pytest


def _insert_strategy(cur, **overrides):
    row = dict(
        title="Test strategy",
        area="Business",
        status="idea",
        source="shannon",
        created_by_user_id=overrides.pop("user_id"),
    )
    row.update(overrides)
    row["updated_by_user_id"] = row["created_by_user_id"]
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO strategies ({cols}) VALUES ({placeholders}) RETURNING id",
        list(row.values()),
    )
    return cur.fetchone()[0]


def test_strategy_with_minimal_fields_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
    pg_conn.commit()
    assert strategy_id is not None


def test_effect_fields_default_to_null_not_zero(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute(
            "SELECT effect_on_net_worth, effect_on_passive_income FROM strategies WHERE id = %s",
            (strategy_id,),
        )
        row = cur.fetchone()
    pg_conn.commit()
    assert row == (None, None)


def test_a_genuine_zero_effect_is_stored_as_the_number_zero(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(
            cur, user_id=owner_user_id, effect_on_net_worth=0, effect_on_passive_income=0,
        )
        cur.execute(
            "SELECT effect_on_net_worth, effect_on_passive_income FROM strategies WHERE id = %s",
            (strategy_id,),
        )
        row = cur.fetchone()
    pg_conn.commit()
    assert row == (0, 0)


def test_status_and_detail_can_be_null_for_unknown_worksheet_entries(pg_conn, owner_user_id):
    """Several seeded entries have "Status: ?" / "Detail: ?" — these must
    be representable as NULL, not forced into a fabricated default."""
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id, status=None, detail=None)
        cur.execute("SELECT status, detail FROM strategies WHERE id = %s", (strategy_id,))
        row = cur.fetchone()
    pg_conn.commit()
    assert row == (None, None)


def test_area_check_rejects_unknown_value(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_strategy(cur, user_id=owner_user_id, area="Not a real area")
    pg_conn.rollback()


def test_area_check_accepts_every_worksheet_heading(pg_conn, owner_user_id):
    for area in ("Work and income", "Relocation", "Business", "Investing", "Property", "Spending"):
        with pg_conn.cursor() as cur:
            strategy_id = _insert_strategy(cur, user_id=owner_user_id, area=area)
        pg_conn.commit()
        assert strategy_id is not None


def test_status_check_rejects_unknown_value(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_strategy(cur, user_id=owner_user_id, status="not-a-real-status")
    pg_conn.rollback()


def test_risks_childcare_eligibility_defaults_to_unknown(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute("SELECT risks_childcare_eligibility FROM strategies WHERE id = %s", (strategy_id,))
        value = cur.fetchone()[0]
    pg_conn.commit()
    assert value == "unknown"


def test_risks_childcare_eligibility_check_rejects_unknown_value(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_strategy(cur, user_id=owner_user_id, risks_childcare_eligibility="maybe")
    pg_conn.rollback()


def test_archived_without_reason_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_strategy(cur, user_id=owner_user_id, status="archived", archived_date="2026-11-03")
    pg_conn.rollback()


def test_archived_without_date_is_rejected(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_strategy(cur, user_id=owner_user_id, status="archived", archived_reason="no longer relevant")
    pg_conn.rollback()


def test_archived_with_both_reason_and_date_is_allowed(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(
            cur, user_id=owner_user_id, status="archived",
            archived_reason="no longer relevant", archived_date="2026-11-03",
        )
    pg_conn.commit()
    assert strategy_id is not None


def test_source_check_rejects_a_value_other_than_shannon_or_asha(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _insert_strategy(cur, user_id=owner_user_id, source="someone_else")
    pg_conn.rollback()


def test_strategy_goal_links_many_to_many(pg_conn, owner_user_id):
    import app.goals_store as goals_store

    goal_id = goals_store.create_goal(
        pg_conn, title="Net worth", type="target", target_value=None, target_date=None,
        source_fact_key="goals.net_worth.target_amount", target_date_fact_key="goals.net_worth.target_date",
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute(
            "INSERT INTO strategy_goal_links (strategy_id, goal_id) VALUES (%s, %s)",
            (strategy_id, goal_id),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT goal_id FROM strategy_goal_links WHERE strategy_id = %s", (strategy_id,))
        assert cur.fetchone()[0] == goal_id


def test_strategy_levers_stores_dimension_delta_from_date(pg_conn, owner_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute(
            "INSERT INTO strategy_levers (strategy_id, dimension, delta, from_date) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (strategy_id, "income.shannon.paye_salary", 10000, "2027-01-01"),
        )
        lever_id = cur.fetchone()[0]
    pg_conn.commit()
    assert lever_id is not None


def test_strategy_deleted_cascades_to_levers_and_links_and_steps(pg_conn, owner_user_id):
    import app.goals_store as goals_store

    goal_id = goals_store.create_goal(
        pg_conn, title="Net worth", type="target", target_value=None, target_date=None,
        source_fact_key="goals.net_worth.target_amount", target_date_fact_key="goals.net_worth.target_date",
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute("INSERT INTO strategy_goal_links (strategy_id, goal_id) VALUES (%s, %s)", (strategy_id, goal_id))
        cur.execute(
            "INSERT INTO strategy_levers (strategy_id, dimension, delta, from_date) VALUES (%s, %s, %s, %s)",
            (strategy_id, "income.shannon.paye_salary", 5000, "2027-01-01"),
        )
        cur.execute(
            "INSERT INTO strategy_steps (strategy_id, title, created_by_user_id) VALUES (%s, %s, %s)",
            (strategy_id, "Do the thing", owner_user_id),
        )
        cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM strategy_goal_links WHERE strategy_id = %s", (strategy_id,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM strategy_levers WHERE strategy_id = %s", (strategy_id,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM strategy_steps WHERE strategy_id = %s", (strategy_id,))
        assert cur.fetchone()[0] == 0


def test_strategy_step_mirrors_tasks_fields(pg_conn, owner_user_id, member_user_id):
    with pg_conn.cursor() as cur:
        strategy_id = _insert_strategy(cur, user_id=owner_user_id)
        cur.execute(
            "INSERT INTO strategy_steps (strategy_id, title, assignee_user_id, created_by_user_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (strategy_id, "Open an account", member_user_id, owner_user_id),
        )
        step_id = cur.fetchone()[0]
    pg_conn.commit()
    assert step_id is not None
