"""
Tests for the facts layer: append-only store, history/audit, UI projection,
and the freshness gate. The freshness-gate tests matter most — that gate is the
thing standing between the household and advice built on stale numbers.

Run: pytest facts_layer/tests/ -v
"""
import pytest
from datetime import date, datetime, timezone, timedelta

from facts_layer import (
    Fact, Source, Unit, FactStore, check_freshness, max_age_for,
)


def mk(key, value, unit, category, source=Source.USER_STATED, as_of=None):
    return Fact.create(key, value, unit, source, category, as_of=as_of)


# ─────────────────────────────────────────────────────────────────────────────
# Fact model
# ─────────────────────────────────────────────────────────────────────────────

def test_fact_key_must_be_dotted():
    with pytest.raises(ValueError):
        Fact.create("nodots", 1, Unit.GBP, Source.USER_STATED, "income")

def test_fact_age_days():
    f = mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income",
           as_of=date(2026, 1, 1))
    assert f.age_days(on=date(2026, 1, 31)) == 30


# ─────────────────────────────────────────────────────────────────────────────
# Store: append-only, current, history
# ─────────────────────────────────────────────────────────────────────────────

def test_set_and_get_roundtrips_types():
    s = FactStore()
    s.set(mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"))
    s.set(mk("property.main.has_mortgage", True, Unit.BOOL, "property"))
    s.set(mk("property.main.rate", 4.07, Unit.PERCENT, "property"))
    s.set(mk("people.partner.name", "Alex", Unit.TEXT, "profile"))

    assert s.get("income.shannon.paye_salary").value == 55000
    assert s.get("income.shannon.paye_salary").value.__class__ is int
    assert s.get("property.main.has_mortgage").value is True
    assert s.get("property.main.rate").value == 4.07
    assert s.get("people.partner.name").value == "Alex"

def test_current_returns_latest_per_key():
    s = FactStore()
    s.set(mk("property.main.value", 490000, Unit.GBP, "valuation"))
    s.set(mk("property.main.value", 500000, Unit.GBP, "valuation"))
    cur = s.current()
    assert cur["property.main.value"].value == 500000

def test_history_is_append_only():
    s = FactStore()
    s.set(mk("property.main.mortgage_balance", 387000, Unit.GBP, "mortgage"))
    s.set(mk("property.main.mortgage_balance", 380000, Unit.GBP, "mortgage"))
    s.set(mk("property.main.mortgage_balance", 375000, Unit.GBP, "mortgage"))
    hist = s.history("property.main.mortgage_balance")
    assert [f.value for f in hist] == [387000, 380000, 375000]

def test_get_missing_returns_none():
    s = FactStore()
    assert s.get("does.not.exist") is None


# ─────────────────────────────────────────────────────────────────────────────
# Store: as_of reconstructs past belief (the audit capability)
# ─────────────────────────────────────────────────────────────────────────────

def test_as_of_reconstructs_past_state():
    s = FactStore()
    # Manually control entered_at by inserting facts with crafted timestamps.
    early = Fact(
        key="property.main.mortgage_balance", value=387000, unit=Unit.GBP,
        source=Source.USER_STATED, category="mortgage",
        as_of=date(2026, 1, 1),
        entered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    late = Fact(
        key="property.main.mortgage_balance", value=375000, unit=Unit.GBP,
        source=Source.USER_STATED, category="mortgage",
        as_of=date(2026, 7, 1),
        entered_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    s.set(early)
    s.set(late)

    # As of March, we still believed the January figure.
    march = s.as_of(datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert march["property.main.mortgage_balance"].value == 387000

    # As of August, the July figure.
    august = s.as_of(datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert august["property.main.mortgage_balance"].value == 375000


# ─────────────────────────────────────────────────────────────────────────────
# Store: UI projection
# ─────────────────────────────────────────────────────────────────────────────

def test_projection_rebuilds_nested_shape():
    s = FactStore()
    s.set(mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"))
    s.set(mk("income.partner.paye_salary", 100000, Unit.GBP_PER_YEAR, "income"))
    proj = s.project()
    assert proj["income"]["shannon"]["paye_salary"] == 55000
    assert proj["income"]["partner"]["paye_salary"] == 100000


# ─────────────────────────────────────────────────────────────────────────────
# Freshness gate — the hard gate
# ─────────────────────────────────────────────────────────────────────────────

def test_policy_lookup():
    assert max_age_for("mortgage") == 30
    assert max_age_for("income") == 90
    assert max_age_for("unknown_category") == 90  # fallback

def test_fresh_data_passes():
    today = date(2026, 6, 1)
    facts = {
        "income.partner.paye_salary": mk(
            "income.partner.paye_salary", 100000, Unit.GBP_PER_YEAR, "income",
            as_of=date(2026, 5, 1),  # 31 days old, income policy 90 -> fresh
        ),
    }
    res = check_freshness(facts, ["income.partner.paye_salary"], on=today)
    assert res.ok is True

def test_stale_data_blocks():
    today = date(2026, 6, 1)
    facts = {
        "property.main.mortgage_balance": mk(
            "property.main.mortgage_balance", 375000, Unit.GBP, "mortgage",
            as_of=date(2026, 1, 1),  # ~151 days old, mortgage policy 30 -> stale
        ),
    }
    res = check_freshness(facts, ["property.main.mortgage_balance"], on=today)
    assert res.ok is False
    assert len(res.stale) == 1
    assert res.stale[0].key == "property.main.mortgage_balance"
    assert res.stale[0].max_age_days == 30
    assert "stale" in res.block_reason()

def test_missing_required_fact_blocks():
    res = check_freshness({}, ["income.shannon.paye_salary"])
    assert res.ok is False
    assert "income.shannon.paye_salary" in res.missing
    assert "missing" in res.block_reason()

def test_boundary_exactly_at_limit_is_fresh():
    today = date(2026, 2, 1)
    facts = {
        "property.main.mortgage_balance": mk(
            "property.main.mortgage_balance", 375000, Unit.GBP, "mortgage",
            as_of=date(2026, 1, 2),  # exactly 30 days, policy 30 -> still fresh
        ),
    }
    res = check_freshness(facts, ["property.main.mortgage_balance"], on=today)
    assert res.ok is True

def test_boundary_one_day_over_is_stale():
    today = date(2026, 2, 1)
    facts = {
        "property.main.mortgage_balance": mk(
            "property.main.mortgage_balance", 375000, Unit.GBP, "mortgage",
            as_of=date(2026, 1, 1),  # 31 days, policy 30 -> stale
        ),
    }
    res = check_freshness(facts, ["property.main.mortgage_balance"], on=today)
    assert res.ok is False

def test_mixed_stale_and_missing_reported_separately():
    today = date(2026, 6, 1)
    facts = {
        "property.main.mortgage_balance": mk(
            "property.main.mortgage_balance", 375000, Unit.GBP, "mortgage",
            as_of=date(2026, 1, 1),  # stale
        ),
    }
    res = check_freshness(
        facts,
        ["property.main.mortgage_balance", "income.shannon.paye_salary"],
        on=today,
    )
    assert res.ok is False
    assert len(res.stale) == 1
    assert "income.shannon.paye_salary" in res.missing


# ─────────────────────────────────────────────────────────────────────────────
# Integration: store + freshness together
# ─────────────────────────────────────────────────────────────────────────────

def test_store_feeds_freshness_gate():
    s = FactStore()
    s.set(mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income",
             as_of=date.today() - timedelta(days=10)))
    s.set(mk("cashflow.emergency_savings", 13000, Unit.GBP, "balance",
             as_of=date.today() - timedelta(days=200)))  # stale (balance=30)

    res = check_freshness(
        s.current(),
        ["income.shannon.paye_salary", "cashflow.emergency_savings"],
    )
    assert res.ok is False
    stale_keys = {sf.key for sf in res.stale}
    assert stale_keys == {"cashflow.emergency_savings"}
