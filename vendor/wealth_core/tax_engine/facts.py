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


class NotVerifiedForYear(Exception):
    """Raised when a calculation tries to USE a TaxYear field that hasn't
    been verified for that year yet (see NotVerified below)."""


class NotVerified:
    """Placeholder for a TaxYear field with no verified value for its year.

    Mere assignment/storage is fine (that's how a TaxYear entry can be
    constructed with some fields verified and others not); any attempt to
    actually USE the value in a calculation — arithmetic, comparison,
    numeric conversion, truthiness — raises NotVerifiedForYear immediately
    with a clear message, instead of a calculation silently going ahead
    with no value (or, worse, a stale figure quietly carried over from a
    prior year).
    """

    def __init__(self, year: str, field_name: str):
        self.year = year
        self.field_name = field_name

    def _raise(self, *_args, **_kwargs):
        raise NotVerifiedForYear(
            f"'{self.field_name}' is not verified for {self.year}. "
            f"Verify the figure against GOV.UK/HMRC and set it on the "
            f"{self.year} TaxYear entry before using it in a calculation."
        )

    def __repr__(self):
        return f"<NotVerified: {self.field_name} for {self.year}>"

    __add__ = __radd__ = __sub__ = __rsub__ = _raise
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _raise
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = _raise
    __pow__ = __rpow__ = __neg__ = __pos__ = __abs__ = _raise
    __lt__ = __le__ = __gt__ = __ge__ = _raise
    __int__ = __float__ = __index__ = __round__ = _raise
    __bool__ = _raise


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


# ─────────────────────────────────────────────────────────────────────────────
# 2026/27
# Verified against GOV.UK, fetched 2026-10-29 (England):
#   https://www.gov.uk/income-tax-rates
#   https://www.gov.uk/national-insurance/how-much-you-pay
#   https://www.gov.uk/child-benefit-rates
#   https://www.gov.uk/child-benefit-tax-charge
# Personal Allowance, income tax bands/rates, employee Class 1 NI, and Child
# Benefit/HICBC are confirmed unchanged from 2025/26 (frozen thresholds).
#
# Everything below that line is NOT verified for 2026/27 (CGT, dividend and
# savings allowances, ISA/JISA, pension annual allowance, trading allowance,
# IHT, SDLT surcharge) — each is a NotVerified placeholder, not a copy of the
# 2025/26 figure. Fill each in only once actually verified against GOV.UK,
# with its own source added above.
# ─────────────────────────────────────────────────────────────────────────────
_2026_27 = TaxYear(
    year="2026/27",
    tax_year_end="2027-04-05",
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
    savings_allowance_basic=NotVerified("2026/27", "savings_allowance_basic"),
    savings_allowance_higher=NotVerified("2026/27", "savings_allowance_higher"),
    dividend_allowance=NotVerified("2026/27", "dividend_allowance"),
    cgt_exemption=NotVerified("2026/27", "cgt_exemption"),
    isa_allowance=NotVerified("2026/27", "isa_allowance"),
    jisa_allowance=NotVerified("2026/27", "jisa_allowance"),
    pension_annual_allowance=NotVerified("2026/27", "pension_annual_allowance"),
    trading_allowance=NotVerified("2026/27", "trading_allowance"),
    cgt_basic_rate_property=NotVerified("2026/27", "cgt_basic_rate_property"),
    cgt_higher_rate_property=NotVerified("2026/27", "cgt_higher_rate_property"),
    cb_weekly_first_child=27.05,
    cb_weekly_additional_child=17.90,
    hicbc_taper_start=60000,
    hicbc_taper_end=80000,
    iht_nil_rate_band=NotVerified("2026/27", "iht_nil_rate_band"),
    iht_residence_nil_rate_band=NotVerified("2026/27", "iht_residence_nil_rate_band"),
    iht_rate=NotVerified("2026/27", "iht_rate"),
    iht_annual_gift_exemption=NotVerified("2026/27", "iht_annual_gift_exemption"),
    sdlt_additional_surcharge=NotVerified("2026/27", "sdlt_additional_surcharge"),
    sources=(
        "https://www.gov.uk/income-tax-rates",
        "https://www.gov.uk/national-insurance/how-much-you-pay",
        "https://www.gov.uk/child-benefit-rates",
        "https://www.gov.uk/child-benefit-tax-charge",
    ),
)


TAX_YEARS = {
    "2025/26": _2025_26,
    "2026/27": _2026_27,
}

DEFAULT_TAX_YEAR = "2026/27"


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
