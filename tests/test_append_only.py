"""
Database-level proof that facts are append-only, independent of whether the
application code ever tries to UPDATE/DELETE. A bug, a bad migration, or a
direct psql session should all be refused the same way.
"""
import psycopg2
import pytest

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402


def _insert_one(pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    fact = Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR,
                        Source.USER_STATED, "income")
    store.set(fact, owner="shannon", entered_by_user_id=owner_user_id)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT id FROM facts WHERE key = %s", (fact.key,))
        return cur.fetchone()[0]


def test_update_is_rejected(pg_conn, owner_user_id):
    fact_id = _insert_one(pg_conn, owner_user_id)
    with pytest.raises(psycopg2.Error):
        with pg_conn.cursor() as cur:
            cur.execute("UPDATE facts SET value_text = '999999' WHERE id = %s", (fact_id,))
    pg_conn.rollback()


def test_delete_is_rejected(pg_conn, owner_user_id):
    fact_id = _insert_one(pg_conn, owner_user_id)
    with pytest.raises(psycopg2.Error):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM facts WHERE id = %s", (fact_id,))
    pg_conn.rollback()
