"""
Pure unit tests for app/goal_progress.py — no Flask, no DB needed, same style
as test_permissions.py. A plain in-memory facts dict stands in for
store.current(); these functions never touch the database themselves.
"""
from datetime import date, timedelta

import pytest

from app.goal_progress import (
    FIRE_ACCESSIBLE_KEYS,
    NET_WORTH_ASSET_KEYS,
    NET_WORTH_DEBT_KEYS,
    PASSIVE_INCOME_ANNUAL_KEYS,
    PASSIVE_INCOME_MONTHLY_KEYS,
    feasibility_for_goal,
    fire_accessible_breakdown,
    household_surplus,
    net_worth_feasibility,
    passive_income_feasibility,
    passive_income_total,
)
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402
from tax_engine import calc_income_tax, deflate_to_today_money  # noqa: E402

TODAY = date(2026, 10, 29)


def fact(key, value, unit, category, as_of=None):
    return Fact.create(key, value, unit, Source.USER_STATED, category, as_of=as_of or TODAY)


def months_from(ref: date, months: int) -> date:
    y, m = ref.year, ref.month + months
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, ref.day)


# ── FIRE accessible breakdown ────────────────────────────────────────────

FULL_FIRE_FACTS = {
    "isa.shannon.cash.value": fact("isa.shannon.cash.value", 5000, Unit.GBP, "balance"),
    "isa.shannon.stocks_shares.value": fact("isa.shannon.stocks_shares.value", 40000, Unit.GBP, "balance"),
    "isa.partner.cash.value": fact("isa.partner.cash.value", 3000, Unit.GBP, "balance"),
    "isa.partner.stocks_shares.value": fact("isa.partner.stocks_shares.value", 20000, Unit.GBP, "balance"),
    "investments.partner.stocks_gia_value": fact("investments.partner.stocks_gia_value", 10000, Unit.GBP, "balance"),
    "investments.shannon.crypto_value": fact("investments.shannon.crypto_value", 2000, Unit.GBP, "balance"),
    "pensions.shannon.current_value": fact("pensions.shannon.current_value", 150000, Unit.GBP, "pension"),
    "pensions.partner.current_value": fact("pensions.partner.current_value", 90000, Unit.GBP, "pension"),
    "cashflow.emergency_savings": fact("cashflow.emergency_savings", 13000, Unit.GBP, "balance"),
    "savings.house_deposit.balance": fact("savings.house_deposit.balance", 22000, Unit.GBP, "balance"),
    "goals.fire.target_number": fact("goals.fire.target_number", 2400000, Unit.GBP, "goal"),
}


def test_fire_accessible_total_sums_only_isa_gia_crypto():
    b = fire_accessible_breakdown(FULL_FIRE_FACTS)
    assert b.accessible_total == 5000 + 40000 + 3000 + 20000 + 10000 + 2000
    assert b.missing_keys == ()


def test_fire_breakdown_excludes_pensions_from_accessible_total():
    facts = dict(FULL_FIRE_FACTS)
    facts["pensions.shannon.current_value"] = fact(
        "pensions.shannon.current_value", 10_000_000, Unit.GBP, "pension"
    )
    b = fire_accessible_breakdown(facts)
    assert b.accessible_total == 80000  # unaffected by the huge pension value
    assert b.pensions_total == 10_000_000 + 90000


def test_fire_breakdown_excludes_emergency_savings_and_house_deposit_from_total():
    facts = dict(FULL_FIRE_FACTS)
    facts["cashflow.emergency_savings"] = fact("cashflow.emergency_savings", 9_000_000, Unit.GBP, "balance")
    facts["savings.house_deposit.balance"] = fact("savings.house_deposit.balance", 9_000_000, Unit.GBP, "balance")
    b = fire_accessible_breakdown(facts)
    assert b.accessible_total == 80000
    assert b.emergency_savings == 9_000_000
    assert b.house_deposit_balance == 9_000_000


def test_fire_breakdown_excludes_junior_isa_even_if_present():
    facts = dict(FULL_FIRE_FACTS)
    facts["isa.junior.value"] = fact("isa.junior.value", 5_000_000, Unit.GBP, "balance")
    b = fire_accessible_breakdown(facts)
    assert b.accessible_total == 80000  # junior ISA never touches the total


def test_fire_breakdown_reports_missing_keys():
    b = fire_accessible_breakdown({})
    assert "isa.shannon.cash.value" in b.missing_keys
    assert "pensions.shannon.current_value" in b.missing_keys
    assert "goals.fire.target_number" in b.missing_keys


# ── Feasibility ──────────────────────────────────────────────────────────

def base_facts(**overrides):
    facts = {
        "income.shannon.paye_salary": fact("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
        "income.partner.paye_salary": fact("income.partner.paye_salary", 70000, Unit.GBP_PER_YEAR, "income"),
        "cashflow.monthly_essentials": fact("cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending"),
        "cashflow.monthly_lifestyle": fact("cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending"),
        "cashflow.monthly_childcare": fact("cashflow.monthly_childcare", 600, Unit.GBP_PER_MONTH, "spending"),
        "cashflow.monthly_other": fact("cashflow.monthly_other", 200, Unit.GBP_PER_MONTH, "spending"),
        "children.0.dob": fact("children.0.dob", "2020-01-01", Unit.DATE, "profile"),
        "children.0.child_benefit_claiming": fact("children.0.child_benefit_claiming", True, Unit.BOOL, "profile"),
        "savings.house_deposit.balance": fact("savings.house_deposit.balance", 22000, Unit.GBP, "balance"),
    }
    facts.update(overrides)
    return facts


DEPOSIT_GOAL = {
    "type": "target",
    "target_value": 70000,
    "target_date": months_from(TODAY, 10),
    "source_fact_key": None,
    "target_date_fact_key": None,
    "progress_fact_keys": ["savings.house_deposit.balance"],
}


def test_golden_house_deposit_example():
    """Hand-computed golden example (see conversation): Shannon £55,000,
    Partner £70,000 (no pension), essentials/lifestyle/childcare/other
    2000/800/600/200, 1 child, £22,000 saved toward a £70,000 deposit due in
    exactly 10 months -> surplus £4,259.83(3), required £4,800/month, short
    by ~£540/month."""
    f = feasibility_for_goal(DEPOSIT_GOAL, base_facts(), on=TODAY, tax_year="2026/27")
    assert f.applicable is True
    assert f.refused is False
    assert f.target == 70000
    assert f.current == 22000
    assert f.shortfall == 48000
    assert f.months_remaining == 10
    assert f.required_monthly == 4800
    assert abs(f.surplus - 4259.833333333333) < 1e-9
    assert f.verdict == "short"
    assert "PAYE salary only" in f.caveat


def test_caveat_states_straight_line_no_growth_inflation_or_tax():
    f = feasibility_for_goal(DEPOSIT_GOAL, base_facts(), on=TODAY, tax_year="2026/27")
    assert "straight-line" in f.caveat
    assert "no investment growth" in f.caveat
    assert "no inflation" in f.caveat
    assert "no tax on investment gains" in f.caveat


def test_not_applicable_for_binary_and_habit_goals():
    for t in ("binary", "habit"):
        f = feasibility_for_goal({"type": t}, base_facts(), on=TODAY)
        assert f.applicable is False


def test_met_when_current_already_covers_target():
    goal = dict(DEPOSIT_GOAL, target_value=10000)
    f = feasibility_for_goal(goal, base_facts(), on=TODAY, tax_year="2026/27")
    assert f.verdict == "met"
    assert f.required_monthly == 0.0


def test_due_now_when_target_date_has_passed():
    goal = dict(DEPOSIT_GOAL, target_date=TODAY - timedelta(days=30))
    f = feasibility_for_goal(goal, base_facts(), on=TODAY, tax_year="2026/27")
    assert f.verdict == "due_now"
    assert f.required_monthly == f.shortfall


def test_on_track_when_surplus_covers_requirement():
    goal = dict(DEPOSIT_GOAL, target_value=30000)  # shortfall only £8,000 over 10mo = £800/mo
    f = feasibility_for_goal(goal, base_facts(), on=TODAY, tax_year="2026/27")
    assert f.verdict == "on_track"


def test_refuses_when_progress_fact_missing_entirely():
    facts = base_facts()
    del facts["savings.house_deposit.balance"]
    f = feasibility_for_goal(DEPOSIT_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert f.missing_keys == ("savings.house_deposit.balance",)


def test_refuses_when_income_fact_missing_entirely():
    facts = base_facts()
    del facts["income.partner.paye_salary"]
    f = feasibility_for_goal(DEPOSIT_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert "income.partner.paye_salary" in f.missing_keys


def test_refuses_naming_fact_backed_target_key_when_missing():
    goal = dict(DEPOSIT_GOAL, target_value=None, source_fact_key="goals.fire.target_number")
    f = feasibility_for_goal(goal, base_facts(), on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert "goals.fire.target_number" in f.missing_keys


def test_caveats_stale_fact_by_name_and_age_but_still_shows_a_number():
    old = TODAY - timedelta(days=100)   # spending's freshness limit is 60 days
    facts = base_facts(
        **{"cashflow.monthly_lifestyle": fact("cashflow.monthly_lifestyle", 800,
                                               Unit.GBP_PER_MONTH, "spending", as_of=old)}
    )
    f = feasibility_for_goal(DEPOSIT_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is False
    assert f.required_monthly == 4800   # number still computed
    assert f.stale and f.stale[0][0] == "cashflow.monthly_lifestyle"
    assert f.stale[0][1] == 100          # age_days
    assert "cashflow.monthly_lifestyle is 100d old (max 60d)" in f.caveat


def test_caveat_names_every_stale_fact_when_more_than_one():
    old = TODAY - timedelta(days=100)
    facts = base_facts(
        **{
            "cashflow.monthly_lifestyle": fact("cashflow.monthly_lifestyle", 800,
                                                Unit.GBP_PER_MONTH, "spending", as_of=old),
            "cashflow.monthly_other": fact("cashflow.monthly_other", 200,
                                            Unit.GBP_PER_MONTH, "spending", as_of=old),
        }
    )
    f = feasibility_for_goal(DEPOSIT_GOAL, facts, on=TODAY, tax_year="2026/27")
    names = {s[0] for s in f.stale}
    assert names == {"cashflow.monthly_lifestyle", "cashflow.monthly_other"}
    assert "cashflow.monthly_lifestyle" in f.caveat and "cashflow.monthly_other" in f.caveat


def test_fact_backed_target_date_is_honoured():
    facts = base_facts(**{
        "goals.fire.target_date": fact("goals.fire.target_date", "2030-10-05", Unit.DATE, "goal"),
        "goals.fire.target_number": fact("goals.fire.target_number", 2_400_000, Unit.GBP, "goal"),
    })
    goal = {
        "type": "target", "target_value": None, "target_date": None,
        "source_fact_key": "goals.fire.target_number",
        "target_date_fact_key": "goals.fire.target_date",
        "progress_fact_keys": [],
    }
    f = feasibility_for_goal(goal, facts, on=TODAY, tax_year="2026/27")
    assert f.target == 2_400_000
    assert f.months_remaining == _whole_months(TODAY, date(2030, 10, 5))


def _whole_months(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


# ── Child Benefit fix (FIX, 2 Nov 2026): this household doesn't receive
# Child Benefit — surplus must exclude it, driven by the existing
# children.0.child_benefit_claiming fact, not by pretending num_children=0
# (the household still has a real child for every other calculation). ──────

def test_not_claiming_child_benefit_lowers_surplus_vs_claiming():
    claiming_facts = base_facts()
    not_claiming_facts = base_facts(**{
        "children.0.child_benefit_claiming": fact(
            "children.0.child_benefit_claiming", False, Unit.BOOL, "profile"
        ),
    })
    f_claiming = feasibility_for_goal(DEPOSIT_GOAL, claiming_facts, on=TODAY, tax_year="2026/27")
    f_not_claiming = feasibility_for_goal(DEPOSIT_GOAL, not_claiming_facts, on=TODAY, tax_year="2026/27")
    assert f_not_claiming.surplus < f_claiming.surplus


def test_not_claiming_child_benefit_matches_engine_directly():
    """The excluded amount must match calc_monthly_surplus(claiming=False)
    exactly — not an approximation."""
    from app.vendor_path import ensure_on_path
    ensure_on_path()
    from recap import calc_monthly_surplus

    facts = base_facts(**{
        "children.0.child_benefit_claiming": fact(
            "children.0.child_benefit_claiming", False, Unit.BOOL, "profile"
        ),
    })
    f = feasibility_for_goal(DEPOSIT_GOAL, facts, on=TODAY, tax_year="2026/27")
    expected = calc_monthly_surplus(
        55000, 70000, 0, 0, 2000, 800, 600, 200,
        tax_year="2026/27", num_children=1, claiming=False,
    )
    assert f.surplus == pytest.approx(expected)


def test_refuses_when_child_benefit_claiming_fact_missing():
    """Required now, like every other surplus input — missing it must
    refuse, never silently assume either way."""
    facts = base_facts()
    del facts["children.0.child_benefit_claiming"]
    f = feasibility_for_goal(DEPOSIT_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert "children.0.child_benefit_claiming" in f.missing_keys


# ── Passive income total (Stage 2 Step 2, Shannon 2 Nov 2026): three new
# monthly boxes (rental/business/investments) plus the existing
# income.*.savings_interest / income.*.dividends facts — the latter are
# GBP_PER_YEAR (confirmed in vendor/wealth_core/migrate/from_v1.py) and
# must be divided by 12, never entered twice. ─────────────────────────────

PASSIVE_INCOME_FACTS = {
    "income.passive.rental": fact("income.passive.rental", 500, Unit.GBP_PER_MONTH, "passive_income"),
    "income.passive.business": fact("income.passive.business", 300, Unit.GBP_PER_MONTH, "passive_income"),
    "income.passive.investments": fact("income.passive.investments", 200, Unit.GBP_PER_MONTH, "passive_income"),
    "income.shannon.savings_interest": fact("income.shannon.savings_interest", 60, Unit.GBP_PER_YEAR, "income"),
    "income.partner.savings_interest": fact("income.partner.savings_interest", 72, Unit.GBP_PER_YEAR, "income"),
    "income.shannon.dividends": fact("income.shannon.dividends", 120, Unit.GBP_PER_YEAR, "income"),
    "income.partner.dividends": fact("income.partner.dividends", 240, Unit.GBP_PER_YEAR, "income"),
}


def test_passive_income_total_sums_three_boxes_plus_interest_and_dividends_monthly():
    total = passive_income_total(PASSIVE_INCOME_FACTS)
    assert total == pytest.approx(500 + 300 + 200 + (60 + 72 + 120 + 240) / 12)


def test_passive_income_total_treats_missing_facts_as_zero():
    assert passive_income_total({}) == 0


def test_passive_income_total_annual_keys_are_divided_by_12_not_added_raw():
    """A regression guard against the easy mistake of forgetting the unit
    conversion — £1,200/yr interest must contribute £100/mo, not £1,200."""
    facts = {"income.shannon.savings_interest": fact(
        "income.shannon.savings_interest", 1200, Unit.GBP_PER_YEAR, "income"
    )}
    assert passive_income_total(facts) == pytest.approx(100)


def test_passive_income_boxes_and_interest_dividends_keys_never_feed_fire_accessible_total():
    """The three new boxes (and the interest/dividends facts they're summed
    with) must never be swept into any net-worth-style asset aggregation —
    FIRE_ACCESSIBLE_KEYS is the one such aggregation that actually runs in
    this app today."""
    for key in PASSIVE_INCOME_MONTHLY_KEYS + PASSIVE_INCOME_ANNUAL_KEYS:
        assert key not in FIRE_ACCESSIBLE_KEYS


# ── Net worth / passive income apex goals (Stage 2 Step 3, 2 Nov 2026) ────
# Both targets are in 2030 money; deflated to today's money before being
# compared against today's-money current figures (never the reverse).

NET_WORTH_GOAL = {
    "type": "target", "target_value": None, "target_date": None,
    "source_fact_key": "goals.net_worth.target_amount",
    "target_date_fact_key": "goals.net_worth.target_date",
    "progress_fact_keys": [],
}

PASSIVE_INCOME_GOAL = {
    "type": "target", "target_value": None, "target_date": None,
    "source_fact_key": "goals.passive_income.target_amount",
    "target_date_fact_key": "goals.passive_income.target_date",
    "progress_fact_keys": [],
}


def net_worth_facts(**overrides):
    facts = base_facts()
    facts.update({
        "cashflow.emergency_savings": fact("cashflow.emergency_savings", 13000, Unit.GBP, "balance"),
        "isa.shannon.stocks_shares.value": fact("isa.shannon.stocks_shares.value", 40000, Unit.GBP, "balance"),
        "isa.shannon.cash.value": fact("isa.shannon.cash.value", 5000, Unit.GBP, "balance"),
        "isa.partner.stocks_shares.value": fact("isa.partner.stocks_shares.value", 20000, Unit.GBP, "balance"),
        "isa.partner.cash.value": fact("isa.partner.cash.value", 3000, Unit.GBP, "balance"),
        "investments.shannon.crypto_value": fact("investments.shannon.crypto_value", 2000, Unit.GBP, "balance"),
        "investments.partner.stocks_gia_value": fact("investments.partner.stocks_gia_value", 10000, Unit.GBP, "balance"),
        "property.main.value": fact("property.main.value", 495000, Unit.GBP, "valuation"),
        "property.main.mortgage_balance": fact("property.main.mortgage_balance", 375000, Unit.GBP, "mortgage"),
        "goals.net_worth.target_amount": fact("goals.net_worth.target_amount", 1_000_000, Unit.GBP, "goal"),
        "goals.net_worth.target_date": fact("goals.net_worth.target_date", "2030-10-05", Unit.DATE, "goal"),
    })
    # savings.house_deposit.balance is already in base_facts() (22000) —
    # it's a net worth asset too, not entered twice.
    facts.update(overrides)
    return facts


# Hand-summed assets: 13000 (emergency) + 40000 + 5000 + 20000 + 3000 + 2000
# + 10000 + 22000 (house deposit) + 495000 (property) = 610000.
# Debt: 375000. Net worth = 235000.
NET_WORTH_CURRENT = 235000


def test_net_worth_current_is_assets_minus_debts():
    f = net_worth_feasibility(NET_WORTH_GOAL, net_worth_facts(), on=TODAY, tax_year="2026/27")
    assert f.refused is False
    assert f.current == NET_WORTH_CURRENT


def test_net_worth_shows_both_2030_and_todays_money_targets():
    f = net_worth_feasibility(NET_WORTH_GOAL, net_worth_facts(), on=TODAY, tax_year="2026/27")
    assert f.target_2030_money == 1_000_000
    expected_today_money = deflate_to_today_money(1_000_000, nominal_year=2030, today_year=TODAY.year)
    assert f.target == pytest.approx(expected_today_money)
    assert f.target < f.target_2030_money  # deflating a future figure reduces it


def test_net_worth_shortfall_is_deflated_target_minus_current():
    f = net_worth_feasibility(NET_WORTH_GOAL, net_worth_facts(), on=TODAY, tax_year="2026/27")
    assert f.shortfall == pytest.approx(f.target - f.current)


def test_net_worth_required_monthly_uses_household_surplus_for_verdict():
    f = net_worth_feasibility(NET_WORTH_GOAL, net_worth_facts(), on=TODAY, tax_year="2026/27")
    assert f.verdict in ("on_track", "short", "met", "due_now")
    if f.verdict in ("on_track", "short"):
        assert f.required_monthly == pytest.approx(f.shortfall / f.months_remaining)


def test_net_worth_refuses_when_target_amount_missing():
    facts = net_worth_facts()
    del facts["goals.net_worth.target_amount"]
    f = net_worth_feasibility(NET_WORTH_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert "goals.net_worth.target_amount" in f.missing_keys


def test_net_worth_refuses_when_target_date_missing():
    facts = net_worth_facts()
    del facts["goals.net_worth.target_date"]
    f = net_worth_feasibility(NET_WORTH_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert "goals.net_worth.target_date" in f.missing_keys


def test_net_worth_refuses_when_surplus_fact_missing():
    facts = net_worth_facts()
    del facts["income.partner.paye_salary"]
    f = net_worth_feasibility(NET_WORTH_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True


def test_net_worth_computed_from_present_assets_when_one_is_missing_not_refused():
    """Missing asset key -> still computed from what's present (same house
    style as fire_accessible_breakdown), not a hard refusal — a missing
    asset isn't known to be zero, so the caveat says so, but a number
    still shows."""
    facts = net_worth_facts()
    del facts["investments.shannon.crypto_value"]
    f = net_worth_feasibility(NET_WORTH_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is False
    assert f.current == NET_WORTH_CURRENT - 2000
    assert "investments.shannon.crypto_value" in f.missing_keys


def test_net_worth_never_uses_the_generic_sum_mechanism():
    """Regression guard: NET_WORTH_ASSET_KEYS/NET_WORTH_DEBT_KEYS must match
    the approved classification table exactly (9 assets, 1 debt)."""
    assert len(NET_WORTH_ASSET_KEYS) == 9
    assert len(NET_WORTH_DEBT_KEYS) == 1
    assert "property.main.mortgage_balance" in NET_WORTH_DEBT_KEYS
    assert "property.main.mortgage_balance" not in NET_WORTH_ASSET_KEYS


def passive_income_goal_facts(**overrides):
    facts = base_facts()
    facts.update(dict(PASSIVE_INCOME_FACTS))
    facts.update({
        "goals.passive_income.target_amount": fact(
            "goals.passive_income.target_amount", 12000, Unit.GBP_PER_MONTH, "goal"
        ),
        "goals.passive_income.target_date": fact(
            "goals.passive_income.target_date", "2030-10-05", Unit.DATE, "goal"
        ),
    })
    facts.update(overrides)
    return facts


# PASSIVE_INCOME_FACTS (defined above): 500+300+200 boxes + (60+72+120+240)/12
PASSIVE_INCOME_CURRENT = 500 + 300 + 200 + (60 + 72 + 120 + 240) / 12


def test_passive_income_current_matches_passive_income_total():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert f.refused is False
    assert f.current == pytest.approx(PASSIVE_INCOME_CURRENT)


def test_passive_income_shows_both_2030_and_todays_money_targets():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert f.target_2030_money == 12000
    expected_today_money = deflate_to_today_money(12000, nominal_year=2030, today_year=TODAY.year)
    assert f.target == pytest.approx(expected_today_money)


def test_passive_income_refuses_when_target_amount_missing():
    facts = passive_income_goal_facts()
    del facts["goals.passive_income.target_amount"]
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is True
    assert "goals.passive_income.target_amount" in f.missing_keys


def test_passive_income_not_refused_when_one_stream_missing():
    """Consistent with Step 2's passive_income_total(): a stream not yet
    set up means zero income from it, not a refusal."""
    facts = passive_income_goal_facts()
    del facts["income.passive.rental"]
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is False
    assert f.current == pytest.approx(PASSIVE_INCOME_CURRENT - 500)


# ── Household surplus shown directly on the Goals page ──────────────────

def test_household_surplus_matches_feasibility_for_goal_surplus():
    f_goal = feasibility_for_goal(DEPOSIT_GOAL, base_facts(), on=TODAY, tax_year="2026/27")
    s = household_surplus(base_facts(), on=TODAY, tax_year="2026/27")
    assert s.refused is False
    assert s.value == pytest.approx(f_goal.surplus)


def test_household_surplus_refuses_when_a_required_fact_is_missing():
    facts = base_facts()
    del facts["cashflow.monthly_essentials"]
    s = household_surplus(facts, on=TODAY, tax_year="2026/27")
    assert s.refused is True
    assert "cashflow.monthly_essentials" in s.missing_keys


# ── Surplus "how this is calculated" breakdown ───────────────────────────
# Display-only detail — must never be a second implementation of the
# surplus formula itself (the result must always equal the shared
# _household_monthly_surplus()/calc_monthly_surplus() value).

def test_surplus_breakdown_result_matches_the_authoritative_surplus_value():
    s = household_surplus(base_facts(), on=TODAY, tax_year="2026/27")
    assert s.breakdown is not None
    assert s.breakdown.result == s.value


def test_surplus_breakdown_shannon_fields_match_calc_income_tax_directly():
    facts = base_facts()
    s = household_surplus(facts, on=TODAY, tax_year="2026/27")
    expected = calc_income_tax(55000, tax_year="2026/27", pension_contribution=0)
    assert s.breakdown.shannon_gross == 55000
    assert s.breakdown.shannon_pension == 0
    assert s.breakdown.shannon_income_tax == expected.income_tax
    assert s.breakdown.shannon_ni == expected.national_insurance
    assert s.breakdown.shannon_take_home == expected.take_home


def test_surplus_breakdown_partner_fields_match_calc_income_tax_directly():
    facts = base_facts()
    s = household_surplus(facts, on=TODAY, tax_year="2026/27")
    expected = calc_income_tax(70000, tax_year="2026/27", pension_contribution=0)
    assert s.breakdown.partner_gross == 70000
    assert s.breakdown.partner_income_tax == expected.income_tax
    assert s.breakdown.partner_ni == expected.national_insurance
    assert s.breakdown.partner_take_home == expected.take_home


def test_surplus_breakdown_shows_the_four_spending_lines():
    s = household_surplus(base_facts(), on=TODAY, tax_year="2026/27")
    assert s.breakdown.essentials == 2000
    assert s.breakdown.lifestyle == 800
    assert s.breakdown.childcare == 600
    assert s.breakdown.other == 200


def test_surplus_breakdown_absent_when_refused():
    facts = base_facts()
    del facts["cashflow.monthly_essentials"]
    s = household_surplus(facts, on=TODAY, tax_year="2026/27")
    assert s.refused is True
    assert s.breakdown is None


def test_standalone_surplus_card_and_feasibility_cards_share_the_same_surplus_value():
    """household_surplus() (the standalone card) and feasibility_for_goal()
    (a goal's feasibility card) must derive surplus identically — both
    call the same shared _household_monthly_surplus()."""
    f_goal = feasibility_for_goal(DEPOSIT_GOAL, base_facts(), on=TODAY, tax_year="2026/27")
    s = household_surplus(base_facts(), on=TODAY, tax_year="2026/27")
    assert s.value == pytest.approx(f_goal.surplus)
    assert s.value == pytest.approx(s.breakdown.result)


# ── Passive income card: no verdict/required-monthly/surplus — comparing
# a monthly income flow's gap against savings-capacity surplus is a
# category error (Shannon, 3 Nov 2026). Net worth is unchanged. ─────────

def test_passive_income_feasibility_has_no_verdict():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert f.verdict == ""


def test_passive_income_feasibility_has_no_required_monthly():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert f.required_monthly is None


def test_passive_income_feasibility_has_no_surplus():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert f.surplus is None


def test_passive_income_feasibility_gap_is_target_minus_current():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert f.shortfall == pytest.approx(max(0.0, f.target - f.current))


def test_passive_income_feasibility_does_not_require_household_surplus_facts():
    """Unlike before, missing income/spending facts must not refuse the
    passive income card — it no longer uses the household surplus at all."""
    facts = passive_income_goal_facts()
    del facts["income.shannon.paye_salary"]
    del facts["cashflow.monthly_essentials"]
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, facts, on=TODAY, tax_year="2026/27")
    assert f.refused is False
    assert f.current == pytest.approx(PASSIVE_INCOME_CURRENT)


def test_passive_income_feasibility_caveat_is_inflation_note_only():
    f = passive_income_feasibility(PASSIVE_INCOME_GOAL, passive_income_goal_facts(), on=TODAY, tax_year="2026/27")
    assert "2030 money" in f.caveat
    assert "straight-line" not in f.caveat.lower()


def test_net_worth_feasibility_still_has_verdict_required_monthly_and_surplus():
    """Regression guard: item 2 only changes the passive income card."""
    f = net_worth_feasibility(NET_WORTH_GOAL, net_worth_facts(), on=TODAY, tax_year="2026/27")
    assert f.verdict != ""
    assert f.required_monthly is not None
    assert f.surplus is not None
