"""
HTTP tests for the confirm-stale walkthrough. Needs a real Postgres (skips
without TEST_DATABASE_URL).
"""
import re
from datetime import date, timedelta

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m
    return m.group(1)


def seed_stale(store, key, value, unit, category, owner, user_id, days_old):
    store.set(
        Fact.create(key, value, unit, Source.USER_STATED, category, as_of=date.today() - timedelta(days=days_old)),
        owner=owner, entered_by_user_id=user_id,
    )


def test_all_caught_up_when_nothing_stale(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )  # fresh (income freshness limit is 90 days, as_of today)
    login(client, owner_user_id)
    resp = client.get("/confirm-stale")
    assert resp.status_code == 200
    assert "All caught up" in resp.data.decode()


def test_owner_sees_most_stale_item_first(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    seed_stale(store, "cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending", "joint", owner_user_id, 100)
    seed_stale(store, "cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending", "joint", owner_user_id, 500)

    login(client, owner_user_id)
    resp = client.get("/confirm-stale")
    body = resp.data.decode()
    assert "2 numbers need confirming" in body
    assert "cashflow.monthly_lifestyle" in body  # the 500-day-old one, shown first
    assert "500d old" in body


def test_confirm_moves_to_the_next_item(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    seed_stale(store, "cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending", "joint", owner_user_id, 100)
    seed_stale(store, "cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending", "joint", owner_user_id, 500)

    login(client, owner_user_id)
    page = client.get("/confirm-stale")
    resp = client.post(
        "/confirm-stale/cashflow.monthly_lifestyle/confirm", data={"csrf_token": token(page)},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/confirm-stale")

    next_page = client.get("/confirm-stale")
    body = next_page.data.decode()
    assert "1 number needs confirming" in body
    assert "cashflow.monthly_essentials" in body
    assert "cashflow.monthly_lifestyle" not in body

    assert store.get("cashflow.monthly_lifestyle").value == 800
    assert store.get("cashflow.monthly_lifestyle").as_of == date.today()


def test_edit_updates_value_and_moves_to_next_item(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    seed_stale(store, "cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending", "joint", owner_user_id, 500)

    login(client, owner_user_id)
    page = client.get("/confirm-stale")
    resp = client.post(
        "/confirm-stale/cashflow.monthly_lifestyle/update",
        data={"value": "950", "csrf_token": token(page)},
    )
    assert resp.status_code == 302
    assert store.get("cashflow.monthly_lifestyle").value == 950
    assert store.get("cashflow.monthly_lifestyle").as_of == date.today()

    after = client.get("/confirm-stale")
    assert "All caught up" in after.data.decode()


def test_member_only_sees_stale_items_she_can_write(client, pg_conn, owner_user_id, member_user_id):
    store = PostgresFactStore(pg_conn)
    seed_stale(store, "income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income", "shannon", owner_user_id, 200)
    seed_stale(store, "cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending", "joint", owner_user_id, 100)
    seed_stale(store, "goals.fire.target_number", 2_400_000, Unit.GBP, "goal", "joint", owner_user_id, 500)

    login(client, member_user_id)
    resp = client.get("/confirm-stale")
    body = resp.data.decode()
    assert "1 number needs confirming" in body
    assert "cashflow.monthly_essentials" in body  # joint, she can write it
    assert "income.shannon.paye_salary" not in body  # his, not hers
    assert "goals.fire.target_number" not in body  # protected, owner-only


def test_owner_sees_all_stale_items_including_protected(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    seed_stale(store, "income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income", "shannon", owner_user_id, 200)
    seed_stale(store, "goals.fire.target_number", 2_400_000, Unit.GBP, "goal", "joint", owner_user_id, 500)

    login(client, owner_user_id)
    resp = client.get("/confirm-stale")
    body = resp.data.decode()
    assert "2 numbers need confirming" in body


def test_member_crafted_post_for_a_fact_she_cannot_write_is_403(client, pg_conn, owner_user_id, member_user_id):
    store = PostgresFactStore(pg_conn)
    seed_stale(store, "income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income", "shannon", owner_user_id, 200)

    login(client, member_user_id)
    page = client.get("/confirm-stale")
    resp = client.post(
        "/confirm-stale/income.shannon.paye_salary/confirm", data={"csrf_token": token(page)},
    )
    assert resp.status_code == 403
    assert store.get("income.shannon.paye_salary").as_of == date.today() - timedelta(days=200)

    resp = client.post(
        "/confirm-stale/income.shannon.paye_salary/update",
        data={"value": "99999", "csrf_token": token(client.get("/confirm-stale"))},
    )
    assert resp.status_code == 403
    assert store.get("income.shannon.paye_salary").value == 55000


def test_unauthenticated_get_redirects_to_login(client):
    resp = client.get("/confirm-stale")
    assert resp.status_code == 302


def test_existing_facts_update_endpoint_behaviour_unchanged_by_refactor(client, pg_conn, owner_user_id):
    """The /facts/<key>/update and /confirm routes must still return 204,
    not a redirect — the refactor that extracted shared helpers for the
    confirm-stale walkthrough must not change their existing contract."""
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 1, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"value": "60000", "csrf_token": token(page)},
    )
    assert resp.status_code == 204

    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm", data={"csrf_token": token(page)},
    )
    assert resp.status_code == 204
