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
from recap import calc_monthly_surplus
from tax_engine import DEFAULT_TAX_YEAR

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
)

PAYE_ONLY_CAVEAT = (
    "Surplus counts PAYE salary only (income.shannon.paye_salary, "
    "income.partner.paye_salary) — dividends, bonuses, self-employment "
    "profit and other income are not included."
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
    current: float | None = None
    shortfall: float | None = None
    months_remaining: int | None = None
    required_monthly: float | None = None
    surplus: float | None = None
    verdict: str = ""              # "met" | "on_track" | "short" | "due_now"
    caveat: str = ""


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

    s_salary = _n(facts["income.shannon.paye_salary"].value)
    p_salary = _n(facts["income.partner.paye_salary"].value)
    s_pension = _optional_annual_pension(facts, "pensions.shannon.monthly_employee")
    p_pension = _optional_annual_pension(facts, "pensions.partner.monthly_employee")
    essentials = _n(facts["cashflow.monthly_essentials"].value)
    lifestyle = _n(facts["cashflow.monthly_lifestyle"].value)
    childcare = _n(facts["cashflow.monthly_childcare"].value)
    other = _n(facts["cashflow.monthly_other"].value)

    surplus = calc_monthly_surplus(
        s_salary, p_salary, s_pension, p_pension,
        essentials, lifestyle, childcare, other,
        tax_year=tax_year, num_children=_num_children(facts),
    )

    stale = tuple((s.key, s.age_days, s.max_age_days) for s in fresh.stale)
    caveat = PAYE_ONLY_CAVEAT
    if stale:
        parts = [f"{key} is {age}d old (max {limit}d)" for key, age, limit in
                  sorted(stale, key=lambda s: -s[1])]
        caveat += " Based on stale data: " + "; ".join(parts) + "."

    shortfall = max(0.0, target_value - current)
    months_remaining = _whole_months_between(ref, target_date)

    if shortfall <= 0:
        verdict, required_monthly = "met", 0.0
    elif months_remaining <= 0:
        verdict, required_monthly = "due_now", shortfall
    else:
        required_monthly = shortfall / months_remaining
        verdict = "on_track" if surplus >= required_monthly else "short"

    return Feasibility(
        stale=stale, target=target_value, current=current, shortfall=shortfall,
        months_remaining=max(0, months_remaining), required_monthly=required_monthly,
        surplus=surplus, verdict=verdict, caveat=caveat,
    )
