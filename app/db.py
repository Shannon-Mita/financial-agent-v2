"""
Thin psycopg2 connection helper. Plain SQL, parameterised queries — no ORM,
matching wealth-core's own stated store philosophy (see vendor/wealth_core
facts_layer/store.py docstring).
"""
import psycopg2
from flask import current_app, g


def get_conn():
    if "db_conn" not in g:
        g.db_conn = psycopg2.connect(current_app.config["DATABASE_URL"])
    return g.db_conn


def close_conn(_exc=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_conn)


def connect(database_url: str):
    """Standalone connection for scripts/tests, outside a Flask app context."""
    return psycopg2.connect(database_url)


def run_migration(conn, sql_path: str):
    with open(sql_path, "r") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
