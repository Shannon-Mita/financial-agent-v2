"""
Tests for the 2027/28-2030/31 TaxYear entries (Shannon, 1 Nov 2026: added now,
not deferred — the household's goals run to 5 Oct 2030, spanning all four).

Verified values (GOV.UK, fetched 2026-11-02): the Personal Allowance
(£12,570), basic rate limit (£50,270 — this file's "taxable income ceiling
for basic rate" convention, i.e. PA + the £37,700 band width legislated in
the OOTLAR), higher/additional rate threshold (£125,140), income tax rates,
NI primary threshold/upper earnings limit (£12,570/£50,270), and NI rates are
all frozen unchanged across all four years.
  - https://www.gov.uk/income-tax-rates
  - https://www.gov.uk/national-insurance/how-much-you-pay
  - https://www.gov.uk/government/publications/budget-2025-overview-of-tax-legislation-and-rates-ootlar/budget-2025-overview-of-tax-legislation-and-rates-ootlar
    (updated 5 Dec 2025): "the Personal Allowance at £12,570 and basic rate
    limit at £37,700 for the 2028 to 2029 to 2030 to 2031 tax years"; "the
    government is maintaining the NICs Primary Threshold (PT) and Lower
    Profits Limit (LPL) at £12,570 from April 2028 until April 2031" and the
    Upper Earnings Limit/Upper Profits Limit at £50,270 over the same period.
    2027/28 is covered by the freeze already in force before this extension.

Everything else (CGT, dividend/savings allowances, ISA/JISA, pension annual
allowance, trading allowance, IHT, SDLT surcharge, and — per Shannon, 1 Nov
2026 — the Child Benefit/HICBC fields too, even though this household no
longer uses them, see app/goal_progress.py) is NotVerified for all four
years, never carried forward from 2026/27.
"""
import pytest
from tax_engine import calc_child_benefit, calc_iht, calc_income_tax, calc_sdlt_surcharge
from tax_engine.facts import NotVerifiedForYear, get_tax_year

YEARS = ("2027/28", "2028/29", "2029/30", "2030/31")

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
    "cb_weekly_first_child",
    "cb_weekly_additional_child",
    "hicbc_taper_start",
    "hicbc_taper_end",
    "iht_nil_rate_band",
    "iht_residence_nil_rate_band",
    "iht_rate",
    "iht_annual_gift_exemption",
    "sdlt_additional_surcharge",
)


@pytest.mark.parametrize("year", YEARS)
def test_year_is_on_file(year):
    assert get_tax_year(year).year == year


@pytest.mark.parametrize("year", YEARS)
def test_frozen_thresholds_match_2026_27(year):
    """Every frozen field is identical across 2026/27 and all four new
    years — same primary source, same figures, not independently re-typed."""
    ty = get_tax_year(year)
    ty_2026 = get_tax_year("2026/27")
    for field_name in (
        "personal_allowance", "basic_rate_limit", "higher_rate_limit",
        "taper_start", "basic_rate", "higher_rate", "additional_rate",
        "ni_primary_threshold", "ni_upper_earnings", "ni_main_rate", "ni_upper_rate",
    ):
        assert getattr(ty, field_name) == getattr(ty_2026, field_name), field_name


@pytest.mark.parametrize("year", YEARS)
def test_golden_105000_salary_matches_2026_27(year):
    """Same frozen bands -> same golden income-tax answer as 2026/27."""
    r = calc_income_tax(105000, tax_year=year)
    r_2026 = calc_income_tax(105000, tax_year="2026/27")
    assert r.income_tax == r_2026.income_tax == 30432
    assert r.take_home == r_2026.take_home


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("field_name", UNVERIFIED_FIELDS)
def test_unverified_field_raises_when_used_in_a_calculation(year, field_name):
    value = getattr(get_tax_year(year), field_name)
    with pytest.raises(NotVerifiedForYear, match=f"not verified for {year.replace('/', '/')}"):
        value + 1


@pytest.mark.parametrize("year", YEARS)
def test_cb_weekly_rates_not_carried_forward_even_though_unused(year):
    """Shannon, 1 Nov 2026: never carry forward an unverified value just
    because this household happens not to need it — calc_child_benefit()
    must still raise if ever called for one of these years with claiming."""
    with pytest.raises(NotVerifiedForYear):
        calc_child_benefit(1, 50000, tax_year=year, claiming=True)


@pytest.mark.parametrize("year", YEARS)
def test_calc_iht_raises_not_verified(year):
    with pytest.raises(NotVerifiedForYear):
        calc_iht(600000, tax_year=year, is_married_or_civil_partner=False)


@pytest.mark.parametrize("year", YEARS)
def test_calc_sdlt_surcharge_raises_not_verified(year):
    with pytest.raises(NotVerifiedForYear):
        calc_sdlt_surcharge(450000, tax_year=year)


def test_2026_27_unaffected_by_new_years_addition():
    r = calc_income_tax(105000, tax_year="2026/27")
    assert r.income_tax == 30432
    assert get_tax_year("2026/27").cb_weekly_first_child == 27.05
