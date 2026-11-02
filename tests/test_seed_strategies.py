"""
Tests for scripts/seed_strategies.py — parses docs/STRATEGY_WORKSHEET.md's
15 entries and loads them, refusing if the strategies table already has
rows (same guard pattern as scripts/restore_data.py). Needs a real
Postgres (skips without TEST_DATABASE_URL) for the DB-touching tests;
the parser tests are pure.
"""
import os

import pytest

import app.strategies_store as strategies_store
from scripts.seed_strategies import (
    WORKSHEET_PATH,
    NotEmptyError,
    parse_worksheet,
    refuse_unless_empty,
    seed_all,
)


@pytest.fixture
def worksheet_text():
    with open(WORKSHEET_PATH) as f:
        return f.read()


def test_parses_exactly_15_entries(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    assert len(entries) == 15


def test_entries_are_numbered_1_through_15_in_order(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    titles = [e["title"] for e in entries]
    assert titles[0] == "New role — Shannon"
    assert titles[-1] == "Spend reduction"


def test_every_entry_has_a_valid_area(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    valid_areas = {"Work and income", "Relocation", "Business", "Investing", "Property", "Spending"}
    for e in entries:
        assert e["area"] in valid_areas, f"{e['title']!r} has area {e['area']!r}"


def test_first_entry_area_is_work_and_income(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    assert entries[0]["area"] == "Work and income"


def test_last_entry_area_is_spending(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    assert entries[-1]["area"] == "Spending"


def test_multiline_detail_is_joined(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    new_role = next(e for e in entries if e["title"] == "New role — Shannon")
    assert "current pay" in new_role["fields"]["Detail"]
    assert "Sales roles for commission" in new_role["fields"]["Detail"]


def test_strategy_8_has_real_zero_effects_not_question_marks(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    mahired = next(e for e in entries if "Mahired" in e["title"])
    assert mahired["fields"]["Effect on net worth"] == "0"
    assert mahired["fields"]["Effect on passive income"] == "0"
    assert mahired["fields"]["From when"] == "n/a"


def test_most_entries_have_unknown_effects(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    new_role = next(e for e in entries if e["title"] == "New role — Shannon")
    assert new_role["fields"]["Effect on net worth"] == "?"


def test_entry_12_and_15_have_unknown_status(worksheet_text):
    entries = parse_worksheet(worksheet_text)
    ramsgate = next(e for e in entries if "Ramsgate" in e["title"])
    spend = next(e for e in entries if e["title"] == "Spend reduction")
    assert ramsgate["fields"]["Status"] == "?"
    assert spend["fields"]["Status"] == "?"


# ── DB-touching: refuse-unless-empty guard + full seed ───────────────────

def test_refuse_unless_empty_raises_when_strategies_has_rows(pg_conn, owner_user_id):
    strategies_store.create_strategy(
        pg_conn, title="Existing", detail=None, area="Business", status="idea",
        work_lives_in="here", effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, source="shannon",
        user_id=owner_user_id,
    )
    with pytest.raises(NotEmptyError):
        refuse_unless_empty(pg_conn)


def test_refuse_unless_empty_passes_on_an_empty_table(pg_conn):
    refuse_unless_empty(pg_conn)  # no exception


def test_seed_all_loads_exactly_15_strategies(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    count = seed_all(pg_conn, entries, owner_id=owner_user_id)
    assert count == 15
    assert len(strategies_store.list_strategies(pg_conn)) == 15


def test_seed_all_refuses_and_writes_nothing_a_second_time(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    with pytest.raises(NotEmptyError):
        seed_all(pg_conn, entries, owner_id=owner_user_id)
    assert len(strategies_store.list_strategies(pg_conn)) == 15  # unchanged, not doubled


def test_seed_all_preserves_unknown_effects_as_null_not_zero(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    new_role = next(s for s in strategies_store.list_strategies(pg_conn) if s["title"] == "New role — Shannon")
    assert new_role["effect_on_net_worth"] is None
    assert new_role["effect_on_passive_income"] is None


def test_seed_all_preserves_strategy_8s_real_zero_as_the_number_zero(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    mahired = next(s for s in strategies_store.list_strategies(pg_conn) if "Mahired" in s["title"])
    assert mahired["effect_on_net_worth"] == 0
    assert mahired["effect_on_passive_income"] == 0
    assert mahired["from_when"] == "n/a"


def test_seed_all_preserves_unknown_status_as_null(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    ramsgate = next(s for s in strategies_store.list_strategies(pg_conn) if "Ramsgate" in s["title"])
    assert ramsgate["status"] is None


def test_seed_all_preserves_unknown_detail_as_null(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    crypto = next(s for s in strategies_store.list_strategies(pg_conn) if s["title"] == "Crypto")
    assert crypto["detail"] is None


def test_seed_all_sets_risks_childcare_eligibility_unknown_for_every_entry(pg_conn, owner_user_id, worksheet_text):
    """Every worksheet entry currently has "Risks childcare eligibility: ?"."""
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    for s in strategies_store.list_strategies(pg_conn):
        assert s["risks_childcare_eligibility"] == "unknown"


def test_seed_all_sets_known_statuses_correctly(pg_conn, owner_user_id, worksheet_text):
    entries = parse_worksheet(worksheet_text)
    seed_all(pg_conn, entries, owner_id=owner_user_id)
    crypto = next(s for s in strategies_store.list_strategies(pg_conn) if s["title"] == "Crypto")
    assert crypto["status"] == "active"
