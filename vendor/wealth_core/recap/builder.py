"""
Monthly recap builder (architecture v0.3, Phase 1).

The first user-facing feature and the proof point for the whole system: it
observes state deterministically and communicates only what matters. No LLM.

Design rules honoured here:
  - FRESHNESS GATE first: if required facts are stale/missing, it does not
    produce advice — it produces a single "confirm your numbers" prompt naming
    exactly what to refresh (§7).
  - MATERIALITY: items below the £ thresholds are suppressed, so the recap is a
    short list of things that matter, not a content dump (§7).
  - DECISION TRIGGERS, not calendar spam: every surfaced item carries a £ impact
    or a deadline. "Here's your monthly update" with nothing actionable is
    exactly what we don't send.

The output is a structured Recap object; a delivery layer renders it to
Telegram/email. Rendering a plain-text version is included for convenience and
testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from facts_layer import FactStore, check_freshness, FreshnessResult
from tax_engine import (
    calc_income_tax, calc_child_benefit, days_until, DEFAULT_TAX_YEAR,
)
from strategy import Objective, project_to_target, TrackStatus


# Materiality thresholds (architecture v0.3 §7).
MIN_ONEOFF_GBP = 500
MIN_RECURRING_GBP = 250
DEADLINE_HORIZON_DAYS = 180


@dataclass(frozen=True)
class RecapItem:
    title: str
    category: str
    impact_gbp: float          # annual £ or one-off £ at stake (0 if deadline-only)
    deadline: str | None       # ISO date, if any
    days_left: int | None
    detail: str
    high_stakes: bool = False  # CGT/SDLT/IHT — always surfaced, always caveated


@dataclass(frozen=True)
class Recap:
    as_of: date
    blocked: bool                       # True if freshness gate stopped us
    block_reason: str
    net_worth: float
    fire_progress_pct: int
    track_status: str = "unknown"       # on_track | at_risk | off_track
    required_monthly: float = 0.0       # extra monthly to close the FIRE gap
    items: tuple[RecapItem, ...] = field(default_factory=tuple)
    suppressed_count: int = 0           # how many low-materiality items we hid

    def to_text(self) -> str:
        if self.blocked:
            return (
                "Wealth recap — paused\n"
                f"I can't produce this month's recap until you confirm some numbers.\n"
                f"Please update: {self.block_reason}"
            )
        lines = [f"Wealth recap — {self.as_of.isoformat()}"]
        lines.append(f"Net worth: £{int(self.net_worth):,}")
        lines.append(f"FIRE progress: {self.fire_progress_pct}%  ({self.track_status.replace('_', ' ')})")
        if self.required_monthly > 0:
            lines.append(f"To close the gap: ~£{int(self.required_monthly):,}/month extra")
        if not self.items:
            lines.append("\nNothing material needs action this month.")
        else:
            lines.append(f"\n{len(self.items)} thing(s) worth your attention:")
            for i, it in enumerate(self.items, 1):
                bits = [f"{i}. {it.title}"]
                if it.impact_gbp:
                    bits.append(f"(~£{int(it.impact_gbp):,})")
                if it.days_left is not None:
                    bits.append(f"— {it.days_left} days left")
                lines.append(" ".join(bits))
                lines.append(f"   {it.detail}")
                if it.high_stakes:
                    lines.append("   ⚠ High-stakes — confirm with a regulated adviser before acting.")
        if self.suppressed_count:
            lines.append(f"\n({self.suppressed_count} minor item(s) below the "
                         f"£{MIN_ONEOFF_GBP} threshold not shown.)")
        return "\n".join(lines)


def _n(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


# Facts the recap needs to compute a household position. If any are stale/missing
# the gate blocks and asks for exactly these.
REQUIRED_KEYS = [
    "income.shannon.paye_salary",
    "income.partner.paye_salary",
    "property.main.value",
    "property.main.mortgage_balance",
    "cashflow.emergency_savings",
    "cashflow.monthly_essentials",
    "cashflow.monthly_lifestyle",
    "cashflow.monthly_childcare",
    "cashflow.monthly_other",
]


def build_recap(
    store: FactStore,
    *,
    tax_year: str = DEFAULT_TAX_YEAR,
    on: date | None = None,
    num_children: int = 1,
) -> Recap:
    ref = on or date.today()
    facts = store.current()

    # 1. Freshness gate — refuse rather than advise on stale numbers.
    fresh: FreshnessResult = check_freshness(facts, REQUIRED_KEYS, on=ref)
    if not fresh.ok:
        return Recap(
            as_of=ref, blocked=True, block_reason=fresh.block_reason(),
            net_worth=0, fire_progress_pct=0,
        )

    proj = store.project()

    def fv(*path, default=0):
        node = proj
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node

    # 2. Deterministic position.
    s_salary = _n(fv("income", "shannon", "paye_salary"))
    p_salary = _n(fv("income", "partner", "paye_salary"))
    s_pension = _n(fv("pensions", "shannon", "monthly_employee")) * 12
    p_pension = _n(fv("pensions", "partner", "monthly_employee")) * 12

    prop_value = _n(fv("property", "main", "value"))
    mortgage = _n(fv("property", "main", "mortgage_balance"))
    equity = max(0.0, prop_value - mortgage)
    cash = _n(fv("cashflow", "emergency_savings"))
    isa = _n(fv("isa", "shannon", "stocks_shares", "value")) + _n(fv("isa", "partner", "stocks_shares", "value"))
    net_worth = equity + cash + isa

    fire_target = _n(fv("goals", "fire", "target_number")) or 4500000
    fire_progress = min(100, round(net_worth / fire_target * 100)) if fire_target else 0

    # Compute both incomes' tax positions once — reused for the 60% check and
    # the Child Benefit check below, AND to derive the real monthly surplus.
    # Surplus was previously read from a fact ("cashflow.monthly_surplus") that
    # nothing ever wrote — it silently defaulted to zero. It is now always
    # DERIVED here, never stored, so it can never drift from the income/spending
    # facts it depends on.
    s_tax = calc_income_tax(s_salary, tax_year=tax_year, pension_contribution=s_pension)
    p_tax = calc_income_tax(p_salary, tax_year=tax_year, pension_contribution=p_pension)
    cb = calc_child_benefit(num_children, p_salary, tax_year=tax_year,
                            pension_contribution=p_pension)
    monthly_take_home = (s_tax.take_home + p_tax.take_home + cb.net_received) / 12
    monthly_spend = (
        _n(fv("cashflow", "monthly_essentials"))
        + _n(fv("cashflow", "monthly_lifestyle"))
        + _n(fv("cashflow", "monthly_childcare"))
        + _n(fv("cashflow", "monthly_other"))
    )
    monthly_surplus = monthly_take_home - monthly_spend

    # FIRE track status via the objective projection.
    target_years = _n(fv("goals", "fire", "target_years")) or 10
    objective = Objective(fire_number=fire_target, target_years=target_years)
    projection = project_to_target(net_worth, monthly_surplus, objective)

    items: list[RecapItem] = []
    suppressed = 0

    def consider(item: RecapItem):
        nonlocal suppressed
        if item.high_stakes:
            items.append(item)
            return
        recurring_ok = item.impact_gbp >= MIN_RECURRING_GBP
        deadline_ok = (
            item.days_left is not None and item.days_left <= DEADLINE_HORIZON_DAYS
        )
        if recurring_ok or deadline_ok:
            items.append(item)
        else:
            suppressed += 1

    # 3. Deterministic checks (a starter set; the catalogue extends these later).

    # Child Benefit clawback recoverable via pension.
    if cb.charge_rate > 0 and num_children > 0:
        lost = cb.annual_entitlement - cb.net_received
        consider(RecapItem(
            title="Child Benefit being clawed back",
            category="tax",
            impact_gbp=lost,
            deadline=None, days_left=None,
            detail=(f"£{int(lost):,}/yr lost to the High Income Charge. "
                    f"Partner pension contributions reduce adjusted net income "
                    f"and can restore it."),
        ))

    # 60% personal-allowance taper zone.
    if p_tax.marginal_rate == 0.60:
        over = p_tax.adjusted_net_income - 100000
        consider(RecapItem(
            title="Partner in the 60% tax trap",
            category="tax",
            impact_gbp=round(over * 0.60),
            deadline=None, days_left=None,
            detail=(f"Adjusted net income £{int(p_tax.adjusted_net_income):,} is in the "
                    f"£100k–£125k band where each £1 is effectively taxed ~60%. "
                    f"Pension contributions unwind this."),
        ))

    # Mortgage fixed-rate expiry deadline.
    fix_end = fv("property", "main", "fixed_rate_end", default=None)
    dleft = days_until(fix_end, on=ref) if fix_end else None
    if dleft is not None and 0 < dleft <= DEADLINE_HORIZON_DAYS:
        consider(RecapItem(
            title="Mortgage fixed rate ending",
            category="property",
            impact_gbp=0,
            deadline=fix_end, days_left=dleft,
            detail=("You can usually lock a new deal up to 6 months ahead. "
                    "Reverting to the variable rate typically raises the payment."),
        ))

    # Emergency fund gap (recurring materiality via the shortfall).
    essentials = _n(fv("cashflow", "monthly_essentials"))
    if essentials > 0:
        target = essentials * 6
        gap = max(0.0, target - cash)
        months = round(cash / essentials, 1) if essentials else 0
        if gap > 0:
            consider(RecapItem(
                title=f"Emergency fund covers {months} months",
                category="cashflow",
                impact_gbp=0,   # not a £-return item; surfaced only if <3 months
                deadline=None, days_left=None,
                detail=f"£{int(gap):,} short of a 6-month buffer (£{int(target):,}).",
            ) if months < 3 else RecapItem(
                title="", category="cashflow", impact_gbp=0,
                deadline=None, days_left=None, detail="",
            ))
            if months >= 3:
                suppressed += 1  # tracked but not material enough to surface

    # Order: high-stakes first, then by £ impact, then by nearest deadline.
    items.sort(key=lambda it: (
        not it.high_stakes,
        -(it.impact_gbp or 0),
        it.days_left if it.days_left is not None else 10**6,
    ))

    return Recap(
        as_of=ref, blocked=False, block_reason="",
        net_worth=net_worth, fire_progress_pct=fire_progress,
        track_status=projection.status.value,
        required_monthly=projection.required_monthly_to_close,
        items=tuple(i for i in items if i.title),
        suppressed_count=suppressed,
    )
