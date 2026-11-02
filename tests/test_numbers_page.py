"""
HTTP-level tests for the Numbers page's grouping/labelling and the
responsive card-grid layout. Needs a real Postgres (skips without
TEST_DATABASE_URL), same as the other route tests.
"""
import os
import re

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def test_facts_grouped_under_the_right_headings(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    seed = [
        ("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
        ("cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending"),
        ("isa.shannon.cash.value", 5000, Unit.GBP, "balance"),
        ("pensions.shannon.current_value", 150000, Unit.GBP, "pension"),
        ("property.main.value", 450000, Unit.GBP, "valuation"),
        ("goals.fire.target_number", 2_400_000, Unit.GBP, "goal"),
        ("people.shannon.dob", "1990-01-01", Unit.DATE, "profile"),
    ]
    for key, val, unit, cat in seed:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat), owner="shannon", entered_by_user_id=owner_user_id)

    login(client, owner_user_id)
    body = client.get("/").data.decode()

    for heading in ("Income", "Spending", "Savings and investments", "Pensions", "Property", "Goals", "Other"):
        assert f">{heading}<" in body, f"missing heading: {heading}"

    # Each fact appears after its group's heading, not before — a loose
    # check that the grouping is actually wired up, not just all headings
    # present somewhere regardless of content.
    assert body.index(">Income<") < body.index("income.shannon.paye_salary")
    assert body.index(">Pensions<") < body.index("pensions.shannon.current_value")
    assert body.index(">Other<") < body.index("people.shannon.dob")


def test_friendly_label_shown_with_raw_key_visible_in_small_text(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("goals.net_worth.target_date", "2030-10-05", Unit.DATE, Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    assert "Net worth target date" in body
    assert 'class="raw-key">goals.net_worth.target_date<' in body


def test_unknown_key_falls_back_to_raw_key_as_its_own_label(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("legacy.meta.taxYear", "2025/26", Unit.TEXT, Source.USER_STATED, "profile"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    # label == raw key for an uncurated fact: the card title and the raw-key
    # line both show it (nothing hides an unlabelled fact).
    assert body.count("legacy.meta.taxYear") >= 2


def test_numbers_page_cards_are_wrapped_in_responsive_grid(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    assert 'class="card-grid"' in body


def test_app_css_defines_the_responsive_grid_breakpoints():
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "app.css")
    with open(css_path) as f:
        css = f.read()
    assert ".card-grid" in css
    assert "grid-template-columns" in css
    assert "@media (min-width: 700px)" in css
    assert "overflow-x: hidden" in css  # no horizontal scroll guard


# ── Stage 2 Step 2: three new passive income boxes ─────────────────────────

PASSIVE_INCOME_KEYS = ("income.passive.rental", "income.passive.business", "income.passive.investments")


def _csrf_token(client):
    page = client.get("/")
    return re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)


def test_passive_income_section_heading_says_after_tax_what_lands_in_account(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(Fact.create("income.passive.rental", 500, Unit.GBP_PER_MONTH, Source.USER_STATED, "passive_income"),
               owner="joint", entered_by_user_id=owner_user_id)
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    assert "after tax" in body.lower() and "what lands in your account" in body.lower()


def test_member_can_create_all_three_passive_income_boxes(client, pg_conn, member_user_id):
    """Asha can create/update all three (Shannon, 2 Nov 2026) — unlike every
    other creatable key, which is owner-only to create."""
    from app.store import PostgresFactStore

    login(client, member_user_id)
    token = _csrf_token(client)
    for key in PASSIVE_INCOME_KEYS:
        resp = client.post(f"/facts/{key}/update", data={"value": "300", "csrf_token": token})
        assert resp.status_code == 303, f"{key}: expected redirect, got {resp.status_code}"
    store = PostgresFactStore(pg_conn)
    for key in PASSIVE_INCOME_KEYS:
        assert store.get(key).value == 300


def test_member_can_update_all_three_after_creation(client, pg_conn, owner_user_id, member_user_id):
    from app.store import PostgresFactStore

    store = PostgresFactStore(pg_conn)
    for key in PASSIVE_INCOME_KEYS:
        store.set(Fact.create(key, 300, Unit.GBP_PER_MONTH, Source.USER_STATED, "passive_income"),
                   owner="joint", entered_by_user_id=owner_user_id)

    login(client, member_user_id)
    token = _csrf_token(client)
    for key in PASSIVE_INCOME_KEYS:
        resp = client.post(f"/facts/{key}/update", data={"value": "450", "csrf_token": token})
        assert resp.status_code == 303
    for key in PASSIVE_INCOME_KEYS:
        assert store.get(key).value == 450


def test_member_sees_not_yet_set_cards_for_passive_income_boxes(client, pg_conn, member_user_id):
    """The 'not yet set' section was previously owner-only, full stop — now
    it must also show a member any key SHE specifically can create."""
    login(client, member_user_id)
    body = client.get("/").data.decode()
    for key in PASSIVE_INCOME_KEYS:
        assert key in body


def test_member_still_does_not_see_owner_only_not_yet_set_cards(client, pg_conn, member_user_id):
    login(client, member_user_id)
    body = client.get("/").data.decode()
    assert "savings.house_deposit.balance" not in body


# ── Stage 2 Step 3 (last): hide all six goals.fire.* boxes — FIRE is
# retired as the apex (net worth + passive income replace it), but the
# facts themselves are never deleted (append-only). ─────────────────────

FIRE_HIDDEN_KEYS = (
    "goals.fire.target_number",
    "goals.fire.swr",
    "goals.fire.target_age",
    "goals.fire.target_years",
    "goals.fire.target_monthly_income",
    "goals.fire.target_date",
)


def test_all_six_fire_boxes_hidden_from_numbers_page_when_set(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    seed = [
        ("goals.fire.target_number", 2_400_000, Unit.GBP),
        ("goals.fire.swr", 4.0, Unit.PERCENT),
        ("goals.fire.target_age", 55, Unit.COUNT),
        ("goals.fire.target_years", 9, Unit.COUNT),
        ("goals.fire.target_monthly_income", 10000, Unit.GBP),
        ("goals.fire.target_date", "2030-10-05", Unit.DATE),
    ]
    for key, val, unit in seed:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, "goal"), owner="joint", entered_by_user_id=owner_user_id)

    login(client, owner_user_id)
    body = client.get("/").data.decode()
    for key in FIRE_HIDDEN_KEYS:
        assert key not in body, f"{key} should be hidden from the Numbers page"


def test_fire_boxes_not_offered_as_not_yet_set_either(client, pg_conn, owner_user_id):
    """goals.fire.target_date is the one FIRE key that's ever been
    creatable — it must not be prompted for any more either, now FIRE is
    retired."""
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    assert "goals.fire.target_date" not in body


def test_fact_still_exists_in_the_store_even_though_hidden(client, pg_conn, owner_user_id):
    """Hidden means not shown/used — never deleted (facts are append-only)."""
    store = PostgresFactStore(pg_conn)
    store.set(Fact.create("goals.fire.target_number", 2_400_000, Unit.GBP, Source.USER_STATED, "goal"),
               owner="joint", entered_by_user_id=owner_user_id)
    login(client, owner_user_id)
    client.get("/")  # hidden from this page's rendering...
    assert store.get("goals.fire.target_number").value == 2_400_000  # ...but never deleted


def test_non_fire_goal_facts_still_render_normally(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(Fact.create("goals.net_worth.target_amount", 1_000_000, Unit.GBP, Source.USER_STATED, "goal"),
               owner="joint", entered_by_user_id=owner_user_id)
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    assert "goals.net_worth.target_amount" in body
