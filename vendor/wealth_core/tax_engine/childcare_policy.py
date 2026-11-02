"""
30-hours funded childcare entitlement — GOV.UK eligibility constants.

Not tax-year scoped (unlike facts.py's TaxYear): this is a standing
eligibility rule, not an annual Budget parameter, so there is no NotVerified
placeholder mechanism here — every field is a fetched, cited figure, or the
module simply doesn't have it yet.

MAINTENANCE: update only with a fetched, dated primary source (never guess,
never carry forward without re-checking) and bump `fetched`.

Verified against GOV.UK, fetched 2026-11-02:
  https://www.gov.uk/30-hours-free-childcare
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChildcareEligibility:
    # Each parent is assessed individually, not the household combined
    # (confirmed by the page's "you or your partner's ... income is over
    # £100,000" wording).
    per_parent_max_adjusted_net_income: int
    per_parent_min_earnings_3_months_21_plus: float
    source: str
    fetched: str


CURRENT = ChildcareEligibility(
    per_parent_max_adjusted_net_income=100_000,
    per_parent_min_earnings_3_months_21_plus=2643.68,
    source="https://www.gov.uk/30-hours-free-childcare",
    fetched="2026-11-02",
)
