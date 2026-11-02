"""
Deterministic goal progress + feasibility (build spec §6). MATHS ONLY — no
growth-rate projection, no strategy suggestions (that's explicitly Stage 2,
see spec §7). Surplus is always derived via wealth-core's own
calc_monthly_surplus() (never a second implementation, never stored) — see
vendor/wealth_core/CHANGES.md's 2026-10-29 REFACTOR entry.

Freshness is a CAVEAT here, not wealth-core's own hard gate (build_recap()
elsewhere still refuses outright on any stale/missing fact): a missing
required fact refuses the calculation and names it; a stale one still shows
a number, with a caveat naming the fact and its age. This is a deliberate,
scoped divergence from wealth-core's all-or-nothing freshness gate — see
the Stage 1 plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import vendor_path  # noqa: F401  (adds vendor/wealth_core to sys.path)
from facts_layer import check_freshness
from recap import calc_monthly_surplus, calc_net_worth
from tax_engine import DEFAULT_TAX_YEAR, calc_income_tax, deflate_to_today_money

# ── FIRE accessible-assets breakdown ────────────────────────────────────
#
# "Accessible" = usable before pension age. Pensions are LOCKED — shown as
# their own line, never summed into the FIRE total. Emergency savings and
# the house deposit pot are also shown as their own lines, not folded into
# the accessible total (Shannon's answer) — money earmarked for a specific
# near-term purpose shouldn't inflate the long-horizon FIRE number. Home
# equity is excluded entirely (not in any list below).
FIRE_ACCESSIBLE_KEYS = (
    "isa.shannon.cash.value",
    "isa.shannon.stocks_shares.value",
    "isa.partner.cash.value",
    "isa.partner.stocks_shares.value",
    "investments.partner.stocks_gia_value",
    "investments.shannon.crypto_value",
)
PENSION_KEYS = ("pensions.shannon.current_value", "pensions.partner.current_value")
EMERGENCY_SAVINGS_KEY = "cashflow.emergency_savings"
HOUSE_DEPOSIT_KEY = "savings.house_deposit.balance"
FIRE_TARGET_KEY = "goals.fire.target_number"


# ── Net worth apex goal (Stage 2 Step 3) ────────────────────────────────
#
# The approved classification table (Shannon, 2 Nov 2026): 9 assets, 1
# debt. Not the generic sum-only progress_fact_keys mechanism — net worth
# needs subtraction, so it gets its own calculation (calc_net_worth, in
# wealth-core) rather than feasibility_for_goal's single-basket sum.
NET_WORTH_ASSET_KEYS = (
    "cashflow.emergency_savings",
    "isa.shannon.stocks_shares.value",
    "isa.shannon.cash.value",
    "isa.partner.stocks_shares.value",
    "isa.partner.cash.value",
    "investments.shannon.crypto_value",
    "investments.partner.stocks_gia_value",
    "savings.house_deposit.balance",
    "property.main.value",
)
NET_WORTH_DEBT_KEYS = (
    "property.main.mortgage_balance",
)
NET_WORTH_TARGET_AMOUNT_KEY = "goals.net_worth.target_amount"
NET_WORTH_TARGET_DATE_KEY = "goals.net_worth.target_date"


# ── Passive income total (Stage 2 Step 2) ───────────────────────────────
#
# Three new monthly boxes (Shannon, 2 Nov 2026) plus the existing
# income.*.savings_interest / income.*.dividends facts — the household's
# interest and dividends are NOT new boxes; they're entered once, here, not
# twice. Those four are GBP_PER_YEAR (vendor/wealth_core/migrate/from_v1.py),
# while the goal is monthly, so they're divided by 12. None of these seven
# keys are asset balances — they are income flows and must never be summed
# into net worth (see FIRE_ACCESSIBLE_KEYS above, a different aggregation).
PASSIVE_INCOME_MONTHLY_KEYS = (
    "income.passive.rental",
    "income.passive.business",
    "income.passive.investments",
)
PASSIVE_INCOME_ANNUAL_KEYS = (
    "income.shannon.savings_interest",
    "income.partner.savings_interest",
    "income.shannon.dividends",
    "income.partner.dividends",
)
PASSIVE_INCOME_TARGET_AMOUNT_KEY = "goals.passive_income.target_amount"
PASSIVE_INCOME_TARGET_DATE_KEY = "goals.passive_income.target_date"


def passive_income_total(facts: dict) -> float:
    monthly, _ = _sum_present(facts, PASSIVE_INCOME_MONTHLY_KEYS)
    annual, _ = _sum_present(facts, PASSIVE_INCOME_ANNUAL_KEYS)
    return monthly + annual / 12


def _n(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _sum_present(facts: dict, keys) -> tuple[float, list[str]]:
    present = [k for k in keys if k in facts]
    missing = [k for k in keys if k not in facts]
    return sum(_n(facts[k].value) for k in present), missing


@dataclass(frozen=True)
class FireBreakdown:
    accessible_total: float
    pensions_total: float
    emergency_savings: float | None
    house_deposit_balance: float | None
    target: float | None
    missing_keys: tuple[str, ...] = field(default_factory=tuple)


def fire_accessible_breakdown(facts: dict) -> FireBreakdown:
    accessible, missing_accessible = _sum_present(facts, FIRE_ACCESSIBLE_KEYS)
    pensions, missing_pensions = _sum_present(facts, PENSION_KEYS)
    emergency = _n(facts[EMERGENCY_SAVINGS_KEY].value) if EMERGENCY_SAVINGS_KEY in facts else None
    house_deposit = _n(facts[HOUSE_DEPOSIT_KEY].value) if HOUSE_DEPOSIT_KEY in facts else None
    target = _n(facts[FIRE_TARGET_KEY].value) if FIRE_TARGET_KEY in facts else None

    missing = list(missing_accessible) + list(missing_pensions)
    if emergency is None:
        missing.append(EMERGENCY_SAVINGS_KEY)
    if house_deposit is None:
        missing.append(HOUSE_DEPOSIT_KEY)
    if target is None:
        missing.append(FIRE_TARGET_KEY)

    return FireBreakdown(
        accessible_total=accessible,
        pensions_total=pensions,
        emergency_savings=emergency,
        house_deposit_balance=house_deposit,
        target=target,
        missing_keys=tuple(missing),
    )


# ── Feasibility check (target-type goals only) ──────────────────────────

SURPLUS_REQUIRED_KEYS = (
    "income.shannon.paye_salary",
    "income.partner.paye_salary",
    "cashflow.monthly_essentials",
    "cashflow.monthly_lifestyle",
    "cashflow.monthly_childcare",
    "cashflow.monthly_other",
    "children.0.child_benefit_claiming",
)

PAYE_ONLY_CAVEAT = (
    "Surplus counts PAYE salary only (income.shannon.paye_salary, "
    "income.partner.paye_salary) — dividends, bonuses, self-employment "
    "profit and other income are not included."
)

STRAIGHT_LINE_CAVEAT = (
    "This is a straight-line calculation: no investment growth, no "
    "inflation, and no tax on investment gains are modelled."
)

_CHILD_INDEX_RE = re.compile(r"^children\.(\d+)\.")


def _num_children(facts: dict) -> int:
    return len({m.group(1) for k in facts for m in [_CHILD_INDEX_RE.match(k)] if m})


def _optional_annual_pension(facts: dict, key: str) -> float:
    return _n(facts[key].value) * 12 if key in facts else 0.0


def _whole_months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


@dataclass(frozen=True)
class Feasibility:
    applicable: bool = True       # False for binary/habit goals — no target to project
    refused: bool = False
    missing_keys: tuple[str, ...] = field(default_factory=tuple)
    stale: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)  # (key, age_days, max_age_days)
    target: float | None = None
    target_2030_money: float | None = None  # only set for inflation-adjusted apex goals
    current: float | None = None
    shortfall: float | None = None
    months_remaining: int | None = None
    required_monthly: float | None = None
    surplus: float | None = None
    verdict: str = ""              # "met" | "on_track" | "short" | "due_now"
    caveat: str = ""


def _household_monthly_surplus(facts: dict, tax_year: str) -> float:
    """Assumes SURPLUS_REQUIRED_KEYS are all present — callers check
    freshness first. Shared by feasibility_for_goal, the two apex
    feasibility functions below, and household_surplus (the Goals page's
    standalone surplus display) — one implementation, not four."""
    s_salary = _n(facts["income.shannon.paye_salary"].value)
    p_salary = _n(facts["income.partner.paye_salary"].value)
    s_pension = _optional_annual_pension(facts, "pensions.shannon.monthly_employee")
    p_pension = _optional_annual_pension(facts, "pensions.partner.monthly_employee")
    essentials = _n(facts["cashflow.monthly_essentials"].value)
    lifestyle = _n(facts["cashflow.monthly_lifestyle"].value)
    childcare = _n(facts["cashflow.monthly_childcare"].value)
    other = _n(facts["cashflow.monthly_other"].value)
    claiming_cb = bool(facts["children.0.child_benefit_claiming"].value)
    return calc_monthly_surplus(
        s_salary, p_salary, s_pension, p_pension,
        essentials, lifestyle, childcare, other,
        tax_year=tax_year, num_children=_num_children(facts), claiming=claiming_cb,
    )


def _shortfall_verdict(current: float, target: float, months_remaining: int, surplus: float):
    """Shared by every target-type feasibility check: shortfall, required
    monthly, and the met/due_now/on_track/short verdict. Returns
    (shortfall, required_monthly, verdict)."""
    shortfall = max(0.0, target - current)
    if shortfall <= 0:
        return shortfall, 0.0, "met"
    if months_remaining <= 0:
        return shortfall, shortfall, "due_now"
    required_monthly = shortfall / months_remaining
    verdict = "on_track" if surplus >= required_monthly else "short"
    return shortfall, required_monthly, verdict


def _stale_caveat(fresh, base_caveat: str) -> tuple[tuple, str]:
    stale = tuple((s.key, s.age_days, s.max_age_days) for s in fresh.stale)
    caveat = base_caveat
    if stale:
        parts = [f"{key} is {age}d old (max {limit}d)" for key, age, limit in
                  sorted(stale, key=lambda s: -s[1])]
        caveat += " Based on stale data: " + "; ".join(parts) + "."
    return stale, caveat


def feasibility_for_goal(goal: dict, facts: dict, *, on: date | None = None,
                          tax_year: str = DEFAULT_TAX_YEAR) -> Feasibility:
    if goal["type"] != "target":
        return Feasibility(applicable=False)

    ref = on or date.today()
    progress_keys = tuple(goal.get("progress_fact_keys") or [])

    required_keys = list(SURPLUS_REQUIRED_KEYS) + list(progress_keys)
    if goal.get("source_fact_key"):
        required_keys.append(goal["source_fact_key"])
    if goal.get("target_date_fact_key"):
        required_keys.append(goal["target_date_fact_key"])

    fresh = check_freshness(facts, required_keys, on=ref)
    if fresh.missing:
        return Feasibility(refused=True, missing_keys=tuple(sorted(fresh.missing)))

    target_value = (
        _n(facts[goal["source_fact_key"]].value) if goal.get("source_fact_key")
        else (_n(goal["target_value"]) if goal.get("target_value") is not None else None)
    )
    target_date = (
        _as_date(facts[goal["target_date_fact_key"]].value) if goal.get("target_date_fact_key")
        else goal.get("target_date")
    )
    if target_value is None or target_date is None:
        return Feasibility(refused=True, missing_keys=("target_value_or_date",))

    current, _ = _sum_present(facts, progress_keys)
    surplus = _household_monthly_surplus(facts, tax_year)
    stale, caveat = _stale_caveat(fresh, PAYE_ONLY_CAVEAT + " " + STRAIGHT_LINE_CAVEAT)
    months_remaining = _whole_months_between(ref, target_date)
    shortfall, required_monthly, verdict = _shortfall_verdict(current, target_value, months_remaining, surplus)

    return Feasibility(
        stale=stale, target=target_value, current=current, shortfall=shortfall,
        months_remaining=max(0, months_remaining), required_monthly=required_monthly,
        surplus=surplus, verdict=verdict, caveat=caveat,
    )


# ── Net worth / passive income apex goals (Stage 2 Step 3) ──────────────
#
# Both goals' targets are in 2030 money (Shannon, 2 Nov 2026) — deflated to
# today's money (via tax_engine.deflate_to_today_money, built in Step 1)
# before comparing against today's-money current figures. Never the
# reverse: projecting today's figures forward to 2030 would be a growth
# projection, out of scope for this maths-only layer.
#
# Missing asset/debt or passive-income-stream facts do NOT refuse the
# calculation — they're summed from whatever's present (same house style
# as fire_accessible_breakdown: a missing asset isn't known to be zero, so
# it's tracked as a caveat, not defaulted). Only the target amount/date and
# the household surplus inputs are hard requirements — there's no sensible
# number to show without those.

INFLATION_CAVEAT = (
    "Target is 2030 money, deflated to today's money using the OBR CPI "
    "forecast before comparing — see the 2030-money figure for the "
    "original target."
)


def net_worth_feasibility(goal: dict, facts: dict, *, on: date | None = None,
                           tax_year: str = DEFAULT_TAX_YEAR) -> Feasibility:
    ref = on or date.today()
    required_keys = list(SURPLUS_REQUIRED_KEYS) + [NET_WORTH_TARGET_AMOUNT_KEY, NET_WORTH_TARGET_DATE_KEY]
    fresh = check_freshness(facts, required_keys, on=ref)
    if fresh.missing:
        return Feasibility(refused=True, missing_keys=tuple(sorted(fresh.missing)))

    target_2030 = _n(facts[NET_WORTH_TARGET_AMOUNT_KEY].value)
    target_date = _as_date(facts[NET_WORTH_TARGET_DATE_KEY].value)
    target_today_money = deflate_to_today_money(target_2030, nominal_year=target_date.year, today_year=ref.year)

    assets, missing_assets = _sum_present(facts, NET_WORTH_ASSET_KEYS)
    debts, missing_debts = _sum_present(facts, NET_WORTH_DEBT_KEYS)
    current = calc_net_worth(assets, debts)

    surplus = _household_monthly_surplus(facts, tax_year)
    stale, caveat = _stale_caveat(fresh, STRAIGHT_LINE_CAVEAT + " " + INFLATION_CAVEAT)
    months_remaining = _whole_months_between(ref, target_date)
    shortfall, required_monthly, verdict = _shortfall_verdict(current, target_today_money, months_remaining, surplus)

    return Feasibility(
        missing_keys=tuple(missing_assets + missing_debts), stale=stale,
        target=target_today_money, target_2030_money=target_2030, current=current,
        shortfall=shortfall, months_remaining=max(0, months_remaining),
        required_monthly=required_monthly, surplus=surplus, verdict=verdict, caveat=caveat,
    )


def passive_income_feasibility(goal: dict, facts: dict, *, on: date | None = None,
                                tax_year: str = DEFAULT_TAX_YEAR) -> Feasibility:
    """No verdict, required_monthly, or surplus (Shannon, 3 Nov 2026):
    comparing a monthly income flow's gap against savings-capacity surplus
    is a category error — surplus growing doesn't make passive income
    grow without an actual strategy. No verdict until strategies exist.
    Net worth is unchanged (it's funded by surplus, so that comparison is
    valid there). This also means the household surplus facts are no
    longer required at all for this card — only the target itself."""
    ref = on or date.today()
    required_keys = [PASSIVE_INCOME_TARGET_AMOUNT_KEY, PASSIVE_INCOME_TARGET_DATE_KEY]
    fresh = check_freshness(facts, required_keys, on=ref)
    if fresh.missing:
        return Feasibility(refused=True, missing_keys=tuple(sorted(fresh.missing)))

    target_2030 = _n(facts[PASSIVE_INCOME_TARGET_AMOUNT_KEY].value)
    target_date = _as_date(facts[PASSIVE_INCOME_TARGET_DATE_KEY].value)
    target_today_money = deflate_to_today_money(target_2030, nominal_year=target_date.year, today_year=ref.year)

    current = passive_income_total(facts)
    missing_streams = [k for k in PASSIVE_INCOME_MONTHLY_KEYS + PASSIVE_INCOME_ANNUAL_KEYS if k not in facts]

    stale, caveat = _stale_caveat(fresh, INFLATION_CAVEAT)
    shortfall = max(0.0, target_today_money - current)

    return Feasibility(
        missing_keys=tuple(missing_streams), stale=stale,
        target=target_today_money, target_2030_money=target_2030, current=current,
        shortfall=shortfall, caveat=caveat,
    )


# ── Household surplus shown directly on the Goals page (Shannon, 2 Nov
# 2026) — standalone, not only reachable by viewing a goal that happens to
# surface it. ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SurplusBreakdown:
    """Display-only detail for the surplus card's "how this is
    calculated" section — never a second implementation of the surplus
    formula. `result` is always exactly _household_monthly_surplus()'s own
    return value; the per-person tax figures reuse calc_income_tax(), the
    same pure building block calc_monthly_surplus() already calls
    internally — recomputing it for display is the same pattern
    build_recap() already uses for its own 60%-trap/CB-clawback checks
    (see vendor/wealth_core/recap/builder.py), not a new formula."""
    shannon_gross: float
    shannon_pension: float
    shannon_income_tax: float
    shannon_ni: float
    shannon_take_home: float
    partner_gross: float
    partner_pension: float
    partner_income_tax: float
    partner_ni: float
    partner_take_home: float
    essentials: float
    lifestyle: float
    childcare: float
    other: float
    result: float


def _household_surplus_breakdown(facts: dict, tax_year: str) -> SurplusBreakdown:
    s_salary = _n(facts["income.shannon.paye_salary"].value)
    p_salary = _n(facts["income.partner.paye_salary"].value)
    s_pension = _optional_annual_pension(facts, "pensions.shannon.monthly_employee")
    p_pension = _optional_annual_pension(facts, "pensions.partner.monthly_employee")
    essentials = _n(facts["cashflow.monthly_essentials"].value)
    lifestyle = _n(facts["cashflow.monthly_lifestyle"].value)
    childcare = _n(facts["cashflow.monthly_childcare"].value)
    other = _n(facts["cashflow.monthly_other"].value)

    s_tax = calc_income_tax(s_salary, tax_year=tax_year, pension_contribution=s_pension)
    p_tax = calc_income_tax(p_salary, tax_year=tax_year, pension_contribution=p_pension)

    return SurplusBreakdown(
        shannon_gross=s_salary, shannon_pension=s_pension,
        shannon_income_tax=s_tax.income_tax, shannon_ni=s_tax.national_insurance,
        shannon_take_home=s_tax.take_home,
        partner_gross=p_salary, partner_pension=p_pension,
        partner_income_tax=p_tax.income_tax, partner_ni=p_tax.national_insurance,
        partner_take_home=p_tax.take_home,
        essentials=essentials, lifestyle=lifestyle, childcare=childcare, other=other,
        result=_household_monthly_surplus(facts, tax_year),
    )


@dataclass(frozen=True)
class SurplusDisplay:
    refused: bool = False
    missing_keys: tuple[str, ...] = field(default_factory=tuple)
    stale: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)
    value: float | None = None
    caveat: str = ""
    breakdown: SurplusBreakdown | None = None


def household_surplus(facts: dict, *, on: date | None = None,
                       tax_year: str = DEFAULT_TAX_YEAR) -> SurplusDisplay:
    ref = on or date.today()
    fresh = check_freshness(facts, SURPLUS_REQUIRED_KEYS, on=ref)
    if fresh.missing:
        return SurplusDisplay(refused=True, missing_keys=tuple(sorted(fresh.missing)))
    stale, caveat = _stale_caveat(fresh, PAYE_ONLY_CAVEAT)
    breakdown = _household_surplus_breakdown(facts, tax_year)
    return SurplusDisplay(stale=stale, value=breakdown.result, caveat=caveat, breakdown=breakdown)
