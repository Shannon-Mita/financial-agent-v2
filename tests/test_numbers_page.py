"""
HTTP-level tests for the Numbers page's grouping/labelling and the
responsive card-grid layout. Needs a real Postgres (skips without
TEST_DATABASE_URL), same as the other route tests.
"""
import os

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
        Fact.create("goals.fire.target_date", "2030-10-05", Unit.DATE, Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    body = client.get("/").data.decode()
    assert "FIRE target date" in body
    assert 'class="raw-key">goals.fire.target_date<' in body


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
