"""
Test suite for the tax engine.

Emphasis on BOUNDARY tests (£99,999 / £100,000 / £100,001 etc.) because tax
systems live at their thresholds and that is exactly where an off-by-one or a
wrong comparison operator causes wrong advice. Golden household scenarios at the
end lock in whole-position outputs so any future change that shifts a headline
number is caught on every deploy.

Run: pytest -v
"""
import pytest
from datetime import date
from tax_engine import (
    calc_income_tax, calc_child_benefit, calc_iht, calc_sdlt_surcharge,
    project_pot, age_from_dob, days_until, get_tax_year, UnknownTaxYear,
)

TY = "2025/26"


# ─────────────────────────────────────────────────────────────────────────────
# Tax-year plumbing
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_tax_year_raises():
    with pytest.raises(UnknownTaxYear):
        get_tax_year("1999/00")

def test_calc_requires_valid_year():
    with pytest.raises(UnknownTaxYear):
        calc_income_tax(50000, tax_year="not-a-year")


# ─────────────────────────────────────────────────────────────────────────────
# Income tax — personal allowance taper boundary (£100k)
# ─────────────────────────────────────────────────────────────────────────────

def test_pa_intact_just_below_taper():
    r = calc_income_tax(99999, tax_year=TY)
    assert r.personal_allowance == 12570
    assert r.marginal_rate == 0.40  # higher-rate but not yet in taper

def test_pa_at_taper_start_exact():
    r = calc_income_tax(100000, tax_year=TY)
    assert r.personal_allowance == 12570  # no taper exactly at the threshold

def test_pa_tapers_just_above():
    r = calc_income_tax(100002, tax_year=TY)
    # £2 over -> lose £1 of PA
    assert r.personal_allowance == 12569
    assert r.marginal_rate == 0.60

def test_pa_fully_gone_at_125140():
    r = calc_income_tax(125140, tax_year=TY)
    assert r.personal_allowance == 0

def test_pa_zero_above_125140():
    r = calc_income_tax(130000, tax_year=TY)
    assert r.personal_allowance == 0
    assert r.marginal_rate == 0.45


# ─────────────────────────────────────────────────────────────────────────────
# Income tax — band boundaries
# ─────────────────────────────────────────────────────────────────────────────

def test_personal_allowance_only_no_tax():
    r = calc_income_tax(12570, tax_year=TY)
    assert r.income_tax == 0

def test_one_pound_into_basic_rate():
    r = calc_income_tax(12571, tax_year=TY)
    assert r.income_tax == round(1 * 0.20)  # £0 after rounding, but taxable=1

def test_basic_rate_ceiling():
    r = calc_income_tax(50270, tax_year=TY)
    # taxable = 50270 - 12570 = 37700, all at 20%
    assert r.income_tax == round(37700 * 0.20)
    assert r.marginal_rate == 0.20

def test_one_pound_into_higher_rate():
    r = calc_income_tax(50271, tax_year=TY)
    assert r.marginal_rate == 0.40

def test_additional_rate_boundary():
    r = calc_income_tax(125141, tax_year=TY)
    assert r.marginal_rate == 0.45


# ─────────────────────────────────────────────────────────────────────────────
# Income tax — pension reduces ANI (the 60%-trap lever)
# ─────────────────────────────────────────────────────────────────────────────

def test_pension_pulls_ani_below_100k():
    r = calc_income_tax(110000, tax_year=TY, pension_contribution=10000)
    assert r.adjusted_net_income == 100000
    assert r.personal_allowance == 12570  # PA fully restored
    assert r.marginal_rate == 0.40

def test_pension_partial_restores_some_pa():
    r = calc_income_tax(110000, tax_year=TY, pension_contribution=4000)
    # ANI 106000 -> 6000 over -> lose 3000 PA -> PA 9570
    assert r.adjusted_net_income == 106000
    assert r.personal_allowance == 9570


# ─────────────────────────────────────────────────────────────────────────────
# Gift Aid extends the basic-rate band
# ─────────────────────────────────────────────────────────────────────────────

def test_gift_aid_extends_basic_band():
    without = calc_income_tax(60000, tax_year=TY)
    with_ga = calc_income_tax(60000, tax_year=TY, gift_aid=8000)
    # Gift aid should move some income from 40% to 20% -> less tax
    assert with_ga.income_tax < without.income_tax


# ─────────────────────────────────────────────────────────────────────────────
# National Insurance boundaries
# ─────────────────────────────────────────────────────────────────────────────

def test_no_ni_at_primary_threshold():
    r = calc_income_tax(12570, tax_year=TY)
    assert r.national_insurance == 0

def test_ni_main_rate_band():
    r = calc_income_tax(50270, tax_year=TY)
    # (50270 - 12570) * 8%
    assert r.national_insurance == round(37700 * 0.08)

def test_ni_upper_rate_applies_above_uel():
    r = calc_income_tax(60270, tax_year=TY)
    expected = 37700 * 0.08 + 10000 * 0.02
    assert r.national_insurance == round(expected)


# ─────────────────────────────────────────────────────────────────────────────
# Child Benefit / HICBC boundaries (£60k–£80k)
# ─────────────────────────────────────────────────────────────────────────────

def test_cb_full_below_taper():
    r = calc_child_benefit(1, 59999, tax_year=TY)
    assert r.charge_rate == 0.0
    assert r.pct_retained == 100
    assert r.net_received == r.annual_entitlement

def test_cb_at_taper_start_still_full():
    r = calc_child_benefit(1, 60000, tax_year=TY)
    assert r.charge_rate == 0.0
    assert r.net_received == r.annual_entitlement

def test_cb_partial_midway():
    r = calc_child_benefit(1, 70000, tax_year=TY)
    assert r.charge_rate == pytest.approx(0.5, abs=0.001)
    assert 40 <= r.pct_retained <= 60

def test_cb_fully_clawed_at_end():
    r = calc_child_benefit(1, 80000, tax_year=TY)
    assert r.charge_rate == 1.0
    assert r.net_received == 0

def test_cb_fully_clawed_above_end():
    r = calc_child_benefit(1, 90000, tax_year=TY)
    assert r.net_received == 0

def test_cb_pension_restores_benefit():
    # £90k earner with £30k pension -> ANI £60k -> full benefit back
    r = calc_child_benefit(1, 90000, tax_year=TY, pension_contribution=30000)
    assert r.net_received == r.annual_entitlement

def test_cb_two_children_more_than_one():
    one = calc_child_benefit(1, 50000, tax_year=TY)
    two = calc_child_benefit(2, 50000, tax_year=TY)
    assert two.annual_entitlement > one.annual_entitlement

def test_cb_zero_children():
    r = calc_child_benefit(0, 50000, tax_year=TY)
    assert r.annual_entitlement == 0
    assert r.net_received == 0


# ─────────────────────────────────────────────────────────────────────────────
# IHT — relationship-aware (the unmarried trap)
# ─────────────────────────────────────────────────────────────────────────────

def test_iht_below_threshold_no_tax():
    r = calc_iht(400000, tax_year=TY, is_married_or_civil_partner=False)
    # NRB 325k + RNRB 175k = 500k threshold
    assert r.total_threshold == 500000
    assert r.tax_due == 0

def test_iht_above_threshold_taxed_at_40():
    r = calc_iht(600000, tax_year=TY, is_married_or_civil_partner=False)
    assert r.taxable_estate == 100000
    assert r.tax_due == 40000

def test_iht_no_rnrb_if_not_to_descendant():
    r = calc_iht(400000, tax_year=TY, is_married_or_civil_partner=False,
                 leaves_home_to_direct_descendant=False)
    assert r.total_threshold == 325000
    assert r.taxable_estate == 75000

def test_iht_spouse_exemption_flag_married():
    r = calc_iht(600000, tax_year=TY, is_married_or_civil_partner=True)
    assert r.spouse_exemption_applied is True

def test_iht_no_spouse_exemption_unmarried():
    r = calc_iht(600000, tax_year=TY, is_married_or_civil_partner=False)
    assert r.spouse_exemption_applied is False


# ─────────────────────────────────────────────────────────────────────────────
# SDLT surcharge
# ─────────────────────────────────────────────────────────────────────────────

def test_sdlt_surcharge_5pct():
    assert calc_sdlt_surcharge(450000, tax_year=TY) == 22500

def test_sdlt_surcharge_scales():
    assert calc_sdlt_surcharge(500000, tax_year=TY) == 25000


# ─────────────────────────────────────────────────────────────────────────────
# Projections
# ─────────────────────────────────────────────────────────────────────────────

def test_project_pot_zero_years_returns_current():
    assert project_pot(10000, 500, 0) == 10000

def test_project_pot_no_contrib_pure_growth():
    # £100k at 7% compounded MONTHLY for 10y ~= 200,966
    v = project_pot(100000, 0, 10, 0.07)
    assert 200000 <= v <= 202000

def test_project_pot_contributions_add_up():
    # £0 start, £1000/mo, 10y, 0% growth = exactly 120,000
    assert project_pot(0, 1000, 10, 0.0) == 120000

def test_project_pot_with_growth_beats_flat():
    flat = project_pot(0, 500, 20, 0.0)
    grown = project_pot(0, 500, 20, 0.07)
    assert grown > flat


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_age_from_dob():
    assert age_from_dob("1990-01-01", on=date(2026, 1, 1)) == 36
    assert age_from_dob("1990-06-15", on=date(2026, 1, 1)) == 35  # birthday not yet

def test_age_from_dob_bad_input():
    assert age_from_dob("") is None
    assert age_from_dob("garbage") is None

def test_days_until():
    assert days_until("2026-01-11", on=date(2026, 1, 1)) == 10

def test_days_until_bad_input():
    assert days_until("") is None


# ─────────────────────────────────────────────────────────────────────────────
# String coercion (the v1 bug class) — engine must never do str + int
# ─────────────────────────────────────────────────────────────────────────────

def test_string_inputs_coerced():
    # SQLite frequently hands back strings; must not raise.
    r = calc_income_tax("55000", tax_year=TY, pension_contribution="3000")
    assert r.gross == 55000
    assert r.adjusted_net_income == 52000

def test_none_inputs_coerced():
    r = calc_income_tax(None, tax_year=TY)
    assert r.gross == 0
    assert r.income_tax == 0


# ─────────────────────────────────────────────────────────────────────────────
# GOLDEN SCENARIOS — whole-position snapshots for the actual household
# These lock in headline outputs; any drift is caught on every deploy.
# ─────────────────────────────────────────────────────────────────────────────

def test_golden_shannon_55k_paye():
    """Shannon: £55k PAYE, no pension yet."""
    r = calc_income_tax(55000, tax_year=TY)
    assert r.income_tax == 9432
    assert r.national_insurance == 3111
    assert r.take_home == 42457
    assert r.marginal_rate == 0.40

def test_golden_partner_100k_paye():
    """Partner: £100k PAYE, no pension contribution."""
    r = calc_income_tax(100000, tax_year=TY)
    assert r.personal_allowance == 12570  # exactly at threshold, no taper
    assert r.marginal_rate == 0.40

def test_golden_partner_hicbc_one_child():
    """Partner at £100k, 1 child -> child benefit fully clawed back."""
    cb = calc_child_benefit(1, 100000, tax_year=TY)
    assert cb.net_received == 0
    assert cb.charge_rate == 1.0

def test_golden_household_unmarried_iht_exposure():
    """Combined estate ~£600k, unmarried -> real IHT exposure, no spouse relief."""
    r = calc_iht(600000, tax_year=TY, is_married_or_civil_partner=False)
    assert r.tax_due == 40000
    assert r.spouse_exemption_applied is False
