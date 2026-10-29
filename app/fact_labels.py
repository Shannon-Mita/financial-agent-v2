"""
Friendly labels + grouping for the Numbers page. Purely presentational —
never used for permissions, freshness, or any calculation; those all still
key off the raw dotted fact key / Fact.category exactly as before.

Grouping reuses each Fact's own `category` (already set correctly by
every writer — the v1 migration, Stage 1's CREATABLE_FACT_SPECS, and every
manual write through the app) rather than a second, parallel key->group
table that could drift out of sync with the real one.
"""
from __future__ import annotations

# Exact fact key -> friendly label. Covers every one of the 47 curated keys
# the v1 migration produces (vendor/wealth_core/migrate/from_v1.py) plus
# Stage 1's two creatable keys. An unknown key (anything not in here, e.g.
# a legacy.* passthrough key) falls back to the raw key — see label_for().
FACT_LABELS: dict[str, str] = {
    # Income
    "income.shannon.paye_salary": "Shannon's PAYE salary",
    "income.shannon.self_employed_profit": "Shannon's self-employed profit",
    "income.shannon.dividends": "Shannon's dividends",
    "income.shannon.savings_interest": "Shannon's savings interest",
    "income.shannon.bonus_expected": "Shannon's expected bonus",
    "income.shannon.gift_aid": "Shannon's Gift Aid donations",
    "income.partner.paye_salary": "Partner's PAYE salary",
    "income.partner.maternity_pay": "Partner's maternity pay",
    "income.partner.dividends": "Partner's dividends",
    "income.partner.savings_interest": "Partner's savings interest",
    "income.partner.bonus_expected": "Partner's expected bonus",
    "income.partner.gift_aid": "Partner's Gift Aid donations",

    # Spending
    "cashflow.monthly_essentials": "Monthly essentials spending",
    "cashflow.monthly_lifestyle": "Monthly lifestyle spending",
    "cashflow.monthly_childcare": "Monthly childcare spending",
    "cashflow.monthly_other": "Other monthly spending",

    # Savings and investments
    "cashflow.emergency_savings": "Emergency savings",
    "isa.shannon.stocks_shares.value": "Shannon's Stocks & Shares ISA",
    "isa.shannon.cash.value": "Shannon's Cash ISA",
    "isa.partner.stocks_shares.value": "Partner's Stocks & Shares ISA",
    "isa.partner.cash.value": "Partner's Cash ISA",
    "isa.junior.value": "Junior ISA",
    "investments.shannon.crypto_value": "Shannon's crypto holdings",
    "investments.partner.stocks_gia_value": "Partner's general investment account",
    "savings.house_deposit.balance": "House deposit savings",

    # Pensions
    "pensions.shannon.current_value": "Shannon's pension value",
    "pensions.shannon.monthly_employee": "Shannon's monthly pension contribution (employee)",
    "pensions.shannon.monthly_employer": "Shannon's monthly pension contribution (employer)",
    "pensions.shannon.has_pension": "Shannon has a pension",
    "pensions.partner.current_value": "Partner's pension value",
    "pensions.partner.monthly_employee": "Partner's monthly pension contribution (employee)",
    "pensions.partner.monthly_employer": "Partner's monthly pension contribution (employer)",
    "pensions.partner.has_pension": "Partner has a pension",
    "pensions.partner.expression_of_wishes_updated": "Partner's pension expression of wishes up to date",

    # Property
    "property.main.value": "Home value",
    "property.main.mortgage_balance": "Mortgage balance",
    "property.main.mortgage_rate": "Mortgage rate",
    "property.main.fixed_rate_end": "Mortgage fixed-rate end date",

    # Goals
    "goals.fire.target_monthly_income": "FIRE target monthly income",
    "goals.fire.target_age": "FIRE target age",
    "goals.fire.swr": "FIRE safe withdrawal rate",
    "goals.fire.target_years": "Years to FIRE target",
    "goals.fire.target_number": "FIRE target number",
    "goals.fire.target_date": "FIRE target date",
    "goals.net_worth.target_amount": "Net worth target",

    # Other (profile — not income/spending/savings/pensions/property/goals)
    "children.0.child_benefit_claiming": "Child 1 — claiming Child Benefit",
    "children.0.dob": "Child 1's date of birth",
    "people.shannon.dob": "Shannon's date of birth",
    "people.partner.dob": "Partner's date of birth",
}

# Fact.category -> Numbers-page group heading. Any category not listed
# (including "profile", and anything unanticipated) falls back to "Other".
CATEGORY_GROUPS: dict[str, str] = {
    "income": "Income",
    "spending": "Spending",
    "balance": "Savings and investments",
    "pension": "Pensions",
    "mortgage": "Property",
    "valuation": "Property",
    "goal": "Goals",
}
DEFAULT_GROUP = "Other"

# Display order for the groups on the page — fixed, not alphabetical, so
# the most load-bearing numbers (income, spending) surface first.
GROUP_ORDER = (
    "Income", "Spending", "Savings and investments", "Pensions",
    "Property", "Goals", "Other",
)


def label_for(key: str) -> str:
    """Friendly label, falling back to the raw key for anything uncurated
    (e.g. a legacy.* passthrough key) — never hides a fact just because it
    has no friendly name yet."""
    return FACT_LABELS.get(key, key)


def group_for(category: str) -> str:
    return CATEGORY_GROUPS.get(category, DEFAULT_GROUP)
