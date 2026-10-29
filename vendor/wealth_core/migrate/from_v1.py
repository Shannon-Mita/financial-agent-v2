"""
Migration: v1 JSON-blob profile -> typed facts_layer facts.

Two passes over the old blob:
  1. CURATED — explicit, hand-checked mappings for every field the tax engine,
     recap, and strategy modules actually read. Correct units, correct
     freshness category, correct type coercion (this is where the old
     empty-string-vs-zero inconsistency gets fixed once, permanently).
  2. LEGACY PASSTHROUGH — everything else in the blob, auto-flattened so no
     data is silently dropped, tagged low-priority so it doesn't participate in
     freshness-gated calculations until someone curates it properly.

The migration also runs a small set of DISCREPANCY CHECKS — places where the
old blob is internally inconsistent (e.g. two different FIRE targets). These
are reported, never silently resolved, because picking one would be the system
making a decision that belongs to the household.

as_of: the old schema stored one `updated_at` for the whole blob, not per
field. We use that single timestamp for every migrated fact — the fairest
faithful representation of what we actually know. Freshness becomes granular
only for facts touched after this migration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from facts_layer import Fact, Source, Unit
from tax_engine import age_from_dob


def _n(value) -> float:
    """The coercion the old blob needed everywhere and didn't have.
    Empty string, None, and missing all become 0."""
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def _get(blob: dict, path: str, default=None):
    node = blob
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


@dataclass(frozen=True)
class Discrepancy:
    description: str
    detail: str


@dataclass(frozen=True)
class MigrationReport:
    curated_count: int
    legacy_count: int
    coerced_fields: tuple[str, ...]     # fields that needed "" -> 0 style coercion
    discrepancies: tuple[Discrepancy, ...]

    def summary(self) -> str:
        lines = [
            f"Migrated {self.curated_count} curated + {self.legacy_count} "
            f"legacy fields.",
        ]
        if self.coerced_fields:
            lines.append(
                f"Coerced {len(self.coerced_fields)} inconsistent field(s): "
                + ", ".join(self.coerced_fields)
            )
        if self.discrepancies:
            lines.append("Discrepancies found (not auto-resolved):")
            for d in self.discrepancies:
                lines.append(f"  - {d.description}: {d.detail}")
        else:
            lines.append("No discrepancies detected.")
        return "\n".join(lines)


# Curated mapping: (old blob path, new fact key, Unit, freshness category)
# Every field the calculation engine actually reads lives here, correctly typed.
_CURATED_NUMERIC = [
    ("income.shannon.payeSalary", "income.shannon.paye_salary", Unit.GBP_PER_YEAR, "income"),
    ("income.shannon.selfEmployedProfit", "income.shannon.self_employed_profit", Unit.GBP_PER_YEAR, "income"),
    ("income.shannon.dividends", "income.shannon.dividends", Unit.GBP_PER_YEAR, "income"),
    ("income.shannon.savingsInterest", "income.shannon.savings_interest", Unit.GBP_PER_YEAR, "income"),
    ("income.shannon.bonusExpected", "income.shannon.bonus_expected", Unit.GBP, "income"),
    ("income.shannon.giftAidDonations", "income.shannon.gift_aid", Unit.GBP_PER_YEAR, "income"),
    ("income.partner.payeSalary", "income.partner.paye_salary", Unit.GBP_PER_YEAR, "income"),
    ("income.partner.maternityPayThisYear", "income.partner.maternity_pay", Unit.GBP_PER_YEAR, "income"),
    ("income.partner.dividends", "income.partner.dividends", Unit.GBP_PER_YEAR, "income"),
    ("income.partner.savingsInterest", "income.partner.savings_interest", Unit.GBP_PER_YEAR, "income"),
    ("income.partner.bonusExpected", "income.partner.bonus_expected", Unit.GBP, "income"),
    ("income.partner.giftAidDonations", "income.partner.gift_aid", Unit.GBP_PER_YEAR, "income"),

    ("property.currentEstimatedValue", "property.main.value", Unit.GBP, "valuation"),
    ("property.mortgageOutstanding", "property.main.mortgage_balance", Unit.GBP, "mortgage"),
    ("property.mortgageRate", "property.main.mortgage_rate", Unit.PERCENT, "mortgage"),

    ("pensions.shannon.currentValue", "pensions.shannon.current_value", Unit.GBP, "pension"),
    ("pensions.shannon.monthlyEmployee", "pensions.shannon.monthly_employee", Unit.GBP_PER_MONTH, "pension"),
    ("pensions.shannon.monthlyEmployer", "pensions.shannon.monthly_employer", Unit.GBP_PER_MONTH, "pension"),
    ("pensions.partner.currentValue", "pensions.partner.current_value", Unit.GBP, "pension"),
    ("pensions.partner.monthlyEmployee", "pensions.partner.monthly_employee", Unit.GBP_PER_MONTH, "pension"),
    ("pensions.partner.monthlyEmployer", "pensions.partner.monthly_employer", Unit.GBP_PER_MONTH, "pension"),

    ("isa.shannon.stocksShares.value", "isa.shannon.stocks_shares.value", Unit.GBP, "balance"),
    ("isa.shannon.cash.value", "isa.shannon.cash.value", Unit.GBP, "balance"),
    ("isa.partner.stocksShares.value", "isa.partner.stocks_shares.value", Unit.GBP, "balance"),
    ("isa.partner.cash.value", "isa.partner.cash.value", Unit.GBP, "balance"),
    ("isa.junior.value", "isa.junior.value", Unit.GBP, "balance"),

    ("investments.shannon.cryptoValue", "investments.shannon.crypto_value", Unit.GBP, "balance"),
    ("investments.partner.stocksGIAValue", "investments.partner.stocks_gia_value", Unit.GBP, "balance"),

    ("cashflow.emergencyCashSavings", "cashflow.emergency_savings", Unit.GBP, "balance"),
    ("cashflow.monthlyEssentials", "cashflow.monthly_essentials", Unit.GBP_PER_MONTH, "spending"),
    ("cashflow.monthlyLifestyle", "cashflow.monthly_lifestyle", Unit.GBP_PER_MONTH, "spending"),
    ("cashflow.monthlyChildcare", "cashflow.monthly_childcare", Unit.GBP_PER_MONTH, "spending"),
    ("cashflow.monthlyOther", "cashflow.monthly_other", Unit.GBP_PER_MONTH, "spending"),

    ("goals.fire.targetMonthlyIncome", "goals.fire.target_monthly_income", Unit.GBP_PER_MONTH, "goal"),
    ("goals.fire.targetAge", "goals.fire.target_age", Unit.COUNT, "goal"),
    ("goals.fire.safeWithdrawalRate", "goals.fire.swr", Unit.PERCENT, "goal"),
    ("goals.netWorth.targetAmount", "goals.net_worth.target_amount", Unit.GBP, "goal"),
]

_CURATED_BOOL = [
    ("pensions.shannon.hasPension", "pensions.shannon.has_pension", "pension"),
    ("pensions.partner.hasPension", "pensions.partner.has_pension", "pension"),
    ("pensions.partner.expressionOfWishesUpdated", "pensions.partner.expression_of_wishes_updated", "pension"),
    ("children.0.childBenefitClaiming", "children.0.child_benefit_claiming", "profile"),
]

_CURATED_DATE = [
    ("property.mortgageFixedRateEndDate", "property.main.fixed_rate_end", "mortgage"),
    ("people.shannon.dob", "people.shannon.dob", "profile"),
    ("people.partner.dob", "people.partner.dob", "profile"),
    ("children.0.dob", "children.0.dob", "profile"),
]


def _flatten(node, prefix=""):
    """Yield (dotted_path, value) for every leaf in a nested dict/list."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _flatten(v, f"{prefix}.{i}" if prefix else str(i))
    else:
        yield prefix, node


def migrate_v1_profile(
    blob: dict,
    as_of: date,
) -> tuple[list[Fact], MigrationReport]:
    facts: list[Fact] = []
    coerced: list[str] = []
    curated_paths_seen: set[str] = set()

    def entered_at() -> datetime:
        return datetime.now(timezone.utc)

    # ── Curated numeric ──────────────────────────────────────────────────────
    for old_path, new_key, unit, category in _CURATED_NUMERIC:
        raw = _get(blob, old_path, 0)
        value = _n(raw)
        if raw in ("", None) :
            coerced.append(old_path)
        facts.append(Fact(
            key=new_key, value=value, unit=unit, source=Source.USER_STATED,
            category=category, as_of=as_of, entered_at=entered_at(),
            note=f"migrated from {old_path}",
        ))
        curated_paths_seen.add(old_path)

    # ── Curated bool ─────────────────────────────────────────────────────────
    for old_path, new_key, category in _CURATED_BOOL:
        raw = _get(blob, old_path, False)
        value = bool(raw)
        facts.append(Fact(
            key=new_key, value=value, unit=Unit.BOOL, source=Source.USER_STATED,
            category=category, as_of=as_of, entered_at=entered_at(),
            note=f"migrated from {old_path}",
        ))
        curated_paths_seen.add(old_path)

    # ── Curated date/text ────────────────────────────────────────────────────
    for old_path, new_key, category in _CURATED_DATE:
        raw = _get(blob, old_path, "")
        facts.append(Fact(
            key=new_key, value=raw or "", unit=Unit.DATE, source=Source.USER_STATED,
            category=category, as_of=as_of, entered_at=entered_at(),
            note=f"migrated from {old_path}",
        ))
        curated_paths_seen.add(old_path)

    # ── Derived: FIRE target_years, and FIRE-formula target_number ─────────────
    s_dob = _get(blob, "people.shannon.dob", "")
    p_dob = _get(blob, "people.partner.dob", "")
    target_age = _n(_get(blob, "goals.fire.targetAge", 0))
    s_age = age_from_dob(s_dob, on=as_of)
    p_age = age_from_dob(p_dob, on=as_of)
    ages = [a for a in (s_age, p_age) if a is not None]
    discrepancies: list[Discrepancy] = []

    if ages and target_age > 0:
        younger = min(ages)
        target_years = max(0, target_age - younger)
        facts.append(Fact(
            key="goals.fire.target_years", value=target_years, unit=Unit.COUNT,
            source=Source.DERIVED, category="goal", as_of=as_of,
            entered_at=entered_at(),
            note="derived from target age minus younger partner's current age",
        ))

    monthly = _n(_get(blob, "goals.fire.targetMonthlyIncome", 0))
    swr = _n(_get(blob, "goals.fire.safeWithdrawalRate", 0))
    if monthly > 0 and swr > 0:
        fire_formula_number = round((monthly * 12) / (swr / 100))
        facts.append(Fact(
            key="goals.fire.target_number", value=fire_formula_number,
            unit=Unit.GBP, source=Source.DERIVED, category="goal", as_of=as_of,
            entered_at=entered_at(),
            note="derived: targetMonthlyIncome * 12 / SWR",
        ))

        stated_net_worth_target = _n(_get(blob, "goals.netWorth.targetAmount", 0))
        if stated_net_worth_target and stated_net_worth_target != fire_formula_number:
            discrepancies.append(Discrepancy(
                description="FIRE target mismatch",
                detail=(
                    f"goals.fire (£{monthly:,.0f}/mo at {swr}% SWR) implies "
                    f"£{fire_formula_number:,.0f}, but goals.netWorth.targetAmount "
                    f"is £{stated_net_worth_target:,.0f}. Both were migrated as "
                    f"separate facts (goals.fire.target_number = formula, "
                    f"goals.net_worth.target_amount = stated). Decide which is "
                    f"the real target."
                ),
            ))

    # ── Legacy passthrough: everything not curated above ────────────────────
    legacy_facts: list[Fact] = []
    for path, value in _flatten(blob):
        if path in curated_paths_seen:
            continue
        if isinstance(value, bool):
            unit = Unit.BOOL
        elif isinstance(value, (int, float)):
            unit = Unit.TEXT  # unit unknown/uncurated; type preserved by store
        else:
            unit = Unit.TEXT
        legacy_facts.append(Fact(
            key=f"legacy.{path}", value=value if not isinstance(value, str) or value != "" else "",
            unit=unit, source=Source.USER_STATED, category="profile",
            as_of=as_of, entered_at=entered_at(),
            note="uncurated passthrough — not used in calculations yet",
        ))

    all_facts = facts + legacy_facts
    report = MigrationReport(
        curated_count=len(facts),
        legacy_count=len(legacy_facts),
        coerced_fields=tuple(coerced),
        discrepancies=tuple(discrepancies),
    )
    return all_facts, report
