"""
Tests for the 2026/27 TaxYear entry.

Verified values (GOV.UK, fetched 2026-10-29, England): Personal Allowance,
income tax bands/rates, employee Class 1 NI, Child Benefit weekly rates, and
HICBC taper are all unchanged from 2025/26 (frozen thresholds). Everything
else (CGT, dividend/savings allowances, ISA/JISA, pension annual allowance,
trading allowance, IHT, SDLT surcharge) is deliberately left unverified for
2026/27 and must raise, not silently reuse the 2025/26 figure.

Golden £45,600 and £105,000 cases are hand-computed against GOV.UK — see
tax_engine/tests/test_engine.py's taper-band-width fix tests for how the
£105,000 case was derived (and the engine bug it caught).
"""
from datetime import date

import pytest
from tax_engine import (
    calc_child_benefit, calc_iht, calc_income_tax, calc_sdlt_surcharge,
)
from tax_engine.facts import DEFAULT_TAX_YEAR, NotVerifiedForYear, get_tax_year

TY = "2026/27"

UNVERIFIED_FIELDS = (
    "savings_allowance_basic",
    "savings_allowance_higher",
    "dividend_allowance",
    "cgt_exemption",
    "isa_allowance",
    "jisa_allowance",
    "pension_annual_allowance",
    "trading_allowance",
    "cgt_basic_rate_property",
    "cgt_higher_rate_property",
    "iht_nil_rate_band",
    "iht_residence_nil_rate_band",
    "iht_rate",
    "iht_annual_gift_exemption",
    "sdlt_additional_surcharge",
)


def _uk_tax_year_label(d: date) -> str:
    """UK tax year (e.g. '2026/27') containing date d. Tax years run 6 Apr -> 5 Apr."""
    start_year = d.year if (d.month, d.day) >= (4, 6) else d.year - 1
    return f"{start_year}/{str(start_year + 1)[-2:]}"


# ─────────────────────────────────────────────────────────────────────────────
# Tax-year plumbing
# ─────────────────────────────────────────────────────────────────────────────

def test_2026_27_is_on_file():
    ty = get_tax_year(TY)
    assert ty.year == "2026/27"


def test_default_tax_year_is_2026_27():
    assert DEFAULT_TAX_YEAR == "2026/27"


def test_default_tax_year_matches_the_tax_year_containing_today():
    """Fails loudly after 5 April 2027 — the signal to add the next entry."""
    assert DEFAULT_TAX_YEAR == _uk_tax_year_label(date.today())


# ─────────────────────────────────────────────────────────────────────────────
# Golden scenarios — hand-computed against GOV.UK, no pension, no other income
# ─────────────────────────────────────────────────────────────────────────────

def test_golden_45600_salary():
    r = calc_income_tax(45600, tax_year=TY)
    assert r.income_tax == 6606
    assert r.national_insurance == 2642
    assert r.take_home == 36352


def test_golden_105000_salary():
    r = calc_income_tax(105000, tax_year=TY)
    assert r.personal_allowance == 10070  # PA tapers down by £2,500
    assert r.income_tax == 30432
    assert r.national_insurance == 4111
    assert r.take_home == 70457


# ─────────────────────────────────────────────────────────────────────────────
# Child Benefit / HICBC
# ─────────────────────────────────────────────────────────────────────────────

def test_cb_annual_entitlement_uses_52_week_convention():
    """Same 52-week convention as 2025/26 (engine.py: annual = weekly * 52)."""
    r = calc_child_benefit(1, 50000, tax_year=TY)
    assert r.annual_entitlement == round(27.05 * 52)


def test_hicbc_50pct_clawback_at_70k():
    r = calc_child_benefit(1, 70000, tax_year=TY)
    assert r.charge_rate == pytest.approx(0.5, abs=0.001)
    assert r.pct_retained == 50


def test_hicbc_full_clawback_at_80k():
    r = calc_child_benefit(1, 80000, tax_year=TY)
    assert r.charge_rate == 1.0
    assert r.net_received == 0


def test_hicbc_full_clawback_above_80k():
    r = calc_child_benefit(1, 90000, tax_year=TY)
    assert r.net_received == 0


# ─────────────────────────────────────────────────────────────────────────────
# Unverified fields must raise, never silently reuse a 2025/26 figure
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field_name", UNVERIFIED_FIELDS)
def test_unverified_field_raises_when_used_in_a_calculation(field_name):
    value = getattr(get_tax_year(TY), field_name)
    with pytest.raises(NotVerifiedForYear, match="not verified for 2026/27"):
        value + 1


def test_calc_iht_raises_not_verified_for_2026_27():
    with pytest.raises(NotVerifiedForYear, match="not verified for 2026/27"):
        calc_iht(600000, tax_year=TY, is_married_or_civil_partner=False)


def test_calc_sdlt_surcharge_raises_not_verified_for_2026_27():
    with pytest.raises(NotVerifiedForYear, match="not verified for 2026/27"):
        calc_sdlt_surcharge(450000, tax_year=TY)


# ─────────────────────────────────────────────────────────────────────────────
# 2025/26 must never be mutated by adding 2026/27
# ─────────────────────────────────────────────────────────────────────────────

def test_2025_26_unaffected_by_2026_27_addition():
    r = calc_income_tax(105000, tax_year="2025/26")
    assert r.income_tax == 30432  # same bands -> same answer, still correct post-fix
    # and its own fields remain plain verified numbers, not sentinels
    assert get_tax_year("2025/26").cgt_exemption == 3000
