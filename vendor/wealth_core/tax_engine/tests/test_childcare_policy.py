"""
Tests for the 30-hours funded childcare eligibility constants.

Not tax-year scoped, unlike TaxYear — this is a standing GOV.UK eligibility
rule, not an annual Budget parameter, so it has no `tax_year` argument and
no NotVerified placeholders: every field here is either fetched and cited,
or not present at all.

Verified against GOV.UK, fetched 2026-11-02:
  https://www.gov.uk/30-hours-free-childcare
"The adjusted net income of you and your partner (if you have one) must
each be under £100,000" (each parent individually, not combined) and each
parent (21+) must individually earn at least £2,643.68 over the 3 months
following application.
"""
from tax_engine.childcare_policy import CURRENT, ChildcareEligibility


def test_current_is_a_childcare_eligibility():
    assert isinstance(CURRENT, ChildcareEligibility)


def test_income_cap_is_per_parent_not_household():
    """£100,000 — each parent individually, not summed across the household
    (Shannon, 1 Nov 2026: 'fetch the eligibility rules (incl. per-parent
    income limits)')."""
    assert CURRENT.per_parent_max_adjusted_net_income == 100_000


def test_minimum_earnings_for_21_plus():
    assert CURRENT.per_parent_min_earnings_3_months_21_plus == 2643.68


def test_source_and_date_are_logged():
    """Shannon, 1 Nov 2026: 'source and date logged' — same discipline as
    TaxYear, never a bare unsourced number."""
    assert CURRENT.source
    assert CURRENT.fetched
