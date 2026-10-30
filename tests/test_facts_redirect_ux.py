"""
UX fix: a POST to /facts/<key>/update or /confirm used to return 204, which
left the page looking completely unchanged with no JS to do anything about
it — the user had no way to tell the save worked without manually
refreshing. Now it redirects (303) back to a validated `next` page with a
flash message and an anchor to the fact's own card, all without any JS.
"""
import re

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


def seed(pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 1, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    return store


# ── Redirect + flash on success ───────────────────────────────────────────

def test_update_redirects_303_with_flash_and_anchor(client, pg_conn, owner_user_id):
    store = seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")

    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"value": "60000", "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/#fact-income.shannon.paye_salary"
    assert store.get("income.shannon.paye_salary").value == 60000

    followed = client.get(resp.headers["Location"])
    assert b"Saved" in followed.data


def test_confirm_redirects_303_with_flash_and_anchor(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")

    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/#fact-income.shannon.paye_salary"

    followed = client.get(resp.headers["Location"])
    assert b"Confirmed" in followed.data


def test_create_if_missing_also_redirects_with_flash_and_anchor(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2030-10-05", "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/#fact-goals.fire.target_date"
    followed = client.get(resp.headers["Location"])
    assert b"Saved" in followed.data


def test_missing_next_field_falls_back_to_numbers_page(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"csrf_token": token(page)},  # no "next" at all
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/#fact-income.shannon.paye_salary"


# ── Open-redirect protection on `next` ────────────────────────────────────

def test_protocol_relative_next_is_rejected_falls_back_to_numbers(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "//evil.com", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    location = resp.headers["Location"]
    assert location == "/#fact-income.shannon.paye_salary"
    assert "evil.com" not in location


def test_full_url_next_is_rejected_falls_back_to_numbers(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "https://evil.com", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    location = resp.headers["Location"]
    assert location == "/#fact-income.shannon.paye_salary"
    assert "evil.com" not in location


def test_backslash_protocol_relative_next_is_rejected(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "/\\evil.com", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    assert "evil.com" not in resp.headers["Location"]


def test_next_without_leading_slash_is_rejected(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "evil.com", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/#fact-income.shannon.paye_salary"


def test_valid_relative_next_is_honoured(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "/confirm-stale", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/confirm-stale#fact-income.shannon.paye_salary"


# ── Validation failures redirect with an error flash, not a bare 400 ─────

def test_non_numeric_value_redirects_with_error_flash_not_400(client, pg_conn, owner_user_id):
    store = seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"value": "not-a-number", "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    followed = client.get(resp.headers["Location"])
    assert b"isn&#39;t a valid value" in followed.data or b"isn't a valid value" in followed.data
    assert store.get("income.shannon.paye_salary").value == 1  # unchanged


def test_non_numeric_value_on_create_if_missing_redirects_with_error_flash(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/savings.house_deposit.balance/update",
        data={"value": "not-a-number", "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    from app.store import PostgresFactStore
    store = PostgresFactStore(pg_conn)
    assert store.get("savings.house_deposit.balance") is None


def test_missing_value_redirects_with_error_flash_not_400(client, pg_conn, owner_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"next": "/", "csrf_token": token(page)},  # no "value" at all
    )
    assert resp.status_code == 303
    followed = client.get(resp.headers["Location"])
    assert b"required" in followed.data


# ── Permission failures still return a hard 403/404, never redirected ────

def test_member_update_of_shannon_owned_fact_is_still_a_hard_403(client, pg_conn, owner_user_id, member_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    t = token(page)

    login(client, member_user_id)
    resp = client.post(
        "/facts/income.shannon.paye_salary/update",
        data={"value": "99999", "next": "/", "csrf_token": t},
    )
    assert resp.status_code == 403
    assert "Location" not in resp.headers


def test_member_confirm_of_shannon_owned_fact_is_still_a_hard_403(client, pg_conn, owner_user_id, member_user_id):
    seed(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get("/")
    t = token(page)

    login(client, member_user_id)
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "/", "csrf_token": t},
    )
    assert resp.status_code == 403
    assert "Location" not in resp.headers


def test_unknown_key_update_is_still_a_hard_404_not_redirected(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/some.made.up.key/update",
        data={"value": "1", "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 404
    assert "Location" not in resp.headers


# ── GBP validation failures show a visible error, through the real route ──

import pytest  # noqa: E402


@pytest.mark.parametrize("bad_value", ["abc", "", "-5", "nan"])
def test_invalid_gbp_value_shows_a_visible_error_not_a_silent_no_op(client, pg_conn, owner_user_id, bad_value):
    store = seed(pg_conn, owner_user_id)  # property-free seed: income.shannon.paye_salary, GBP_PER_YEAR
    store.set(
        Fact.create("property.main.mortgage_balance", 375000, Unit.GBP, Source.USER_STATED, "mortgage"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/property.main.mortgage_balance/update",
        data={"value": bad_value, "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303  # redirect, not a bare 400/500
    followed = client.get(resp.headers["Location"])
    body = followed.data.decode()
    assert "flash error" in body or 'class="flash error' in body
    assert "isn&#39;t a valid value" in body or "isn't a valid value" in body
    assert store.get("property.main.mortgage_balance").value == 375000  # unchanged
