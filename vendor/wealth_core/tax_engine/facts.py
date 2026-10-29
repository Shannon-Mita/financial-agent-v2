"""
Tax facts — hardcoded, versioned by UK tax year.

DESIGN RULE (from architecture v0.3, Layer 2):
  These parameters are the ONLY source of tax thresholds, rates and bands in the
  system. No LLM and no retrieval step may supply or override them. Every value
  carries the tax year it applies to and a primary source. `tax_year` is a
  mandatory argument to every calculation in engine.py.

MAINTENANCE:
  After each Budget / HMRC update, add a new TAX_YEARS entry (do not mutate an
  old one — history must be preserved), then re-run the golden-scenario tests.

Sources are recorded per parameter block. Verify against gov.uk / HMRC for the
relevant year before relying on any figure for a real decision.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaxYear:
    """All headline UK personal-tax parameters for one tax year (England)."""
    year: str                       # e.g. "2025/26"
    tax_year_end: str               # ISO date of 5 April year-end

    # Income tax (England/NI/Wales rest-of-UK bands)
    personal_allowance: int
    basic_rate_limit: int           # taxable income ceiling for basic rate
    higher_rate_limit: int          # taxable income ceiling for higher rate
    taper_start: int                # PA taper begins (adjusted net income)
    basic_rate: float
    higher_rate: float
    additional_rate: float

    # National Insurance (Class 1 primary, employee)
    ni_primary_threshold: int
    ni_upper_earnings: int
    ni_main_rate: float
    ni_upper_rate: float

    # Allowances / wrappers
    savings_allowance_basic: int
    savings_allowance_higher: int
    dividend_allowance: int
    cgt_exemption: int
    isa_allowance: int
    jisa_allowance: int
    pension_annual_allowance: int
    trading_allowance: int

    # Capital Gains Tax (residential property rates)
    cgt_basic_rate_property: float
    cgt_higher_rate_property: float

    # Child Benefit (High Income Child Benefit Charge)
    cb_weekly_first_child: float
    cb_weekly_additional_child: float
    hicbc_taper_start: int
    hicbc_taper_end: int

    # Inheritance Tax
    iht_nil_rate_band: int
    iht_residence_nil_rate_band: int
    iht_rate: float
    iht_annual_gift_exemption: int

    # SDLT additional-property surcharge (England, from 31 Oct 2024)
    sdlt_additional_surcharge: float

    sources: tuple = field(default_factory=tuple)


# ─────────────────────────────────────────────────────────────────────────────
# 2025/26
# Verify against:
#   https://www.gov.uk/income-tax-rates
#   https://www.gov.uk/government/publications/rates-and-allowances-income-tax
#   https://www.gov.uk/child-benefit-tax-charge
#   https://www.gov.uk/capital-gains-tax
#   https://www.gov.uk/inheritance-tax
#   https://www.gov.uk/stamp-duty-land-tax
# ─────────────────────────────────────────────────────────────────────────────
_2025_26 = TaxYear(
    year="2025/26",
    tax_year_end="2026-04-05",
    personal_allowance=12570,
    basic_rate_limit=50270,
    higher_rate_limit=125140,
    taper_start=100000,
    basic_rate=0.20,
    higher_rate=0.40,
    additional_rate=0.45,
    ni_primary_threshold=12570,
    ni_upper_earnings=50270,
    ni_main_rate=0.08,
    ni_upper_rate=0.02,
    savings_allowance_basic=1000,
    savings_allowance_higher=500,
    dividend_allowance=500,
    cgt_exemption=3000,
    isa_allowance=20000,
    jisa_allowance=9000,
    pension_annual_allowance=60000,
    trading_allowance=1000,
    cgt_basic_rate_property=0.18,
    cgt_higher_rate_property=0.24,
    cb_weekly_first_child=26.05,
    cb_weekly_additional_child=17.25,
    hicbc_taper_start=60000,
    hicbc_taper_end=80000,
    iht_nil_rate_band=325000,
    iht_residence_nil_rate_band=175000,
    iht_rate=0.40,
    iht_annual_gift_exemption=3000,
    sdlt_additional_surcharge=0.05,
    sources=(
        "https://www.gov.uk/income-tax-rates",
        "https://www.gov.uk/child-benefit-tax-charge",
        "https://www.gov.uk/capital-gains-tax",
        "https://www.gov.uk/inheritance-tax",
        "https://www.gov.uk/stamp-duty-land-tax",
    ),
)


TAX_YEARS = {
    "2025/26": _2025_26,
}

DEFAULT_TAX_YEAR = "2025/26"


class UnknownTaxYear(KeyError):
    """Raised when a calculation is requested for a tax year not on file."""


def get_tax_year(year: str = DEFAULT_TAX_YEAR) -> TaxYear:
    """Return the frozen parameter set for a tax year, or raise loudly.

    We raise rather than silently defaulting: a calculation against the wrong
    year is exactly the class of error this layer exists to prevent.
    """
    try:
        return TAX_YEARS[year]
    except KeyError:
        raise UnknownTaxYear(
            f"No tax parameters on file for '{year}'. "
            f"Available: {sorted(TAX_YEARS)}. Add a TaxYear entry before "
            f"running calculations for this year."
        )
