"""
Pure unit tests for app/goal_progress.py — no Flask, no DB needed, same style
as test_permissions.py. A plain in-memory facts dict stands in for
store.current(); these functions never touch the database themselves.
"""
from datetime import date, timedelta

from app.goal_progress import fire_accessible_breakdown, feasibility_for_goal
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

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
