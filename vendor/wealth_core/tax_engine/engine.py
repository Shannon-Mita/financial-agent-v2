"""
Deterministic UK personal-tax calculation engine (architecture v0.3, Layer 3).

Every public function takes an explicit `tax_year` and pulls all parameters from
facts.py. No thresholds or rates are written inline here. Functions are pure:
same inputs -> same outputs, no I/O, no globals.

These are estimates of headline personal-tax positions for planning. They are
not a substitute for regulated advice and deliberately do not attempt to model
every edge case (e.g. Scottish rates, blind person's allowance, marriage
allowance, student loan, specific NI categories). Scope is documented per
function.
"""

from dataclasses import dataclass
from datetime import date
from .facts import get_tax_year, TaxYear


def _n(value) -> float:
    """Coerce any stored value (SQLite often returns strings) to a number.

    Centralised here so no calculation ever does string+int arithmetic — the
    single most common bug class in the v1 build.
    """
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Income tax + NI
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IncomeTaxResult:
    gross: float
    adjusted_net_income: float      # gross less deductible pension & grossed gift aid
    personal_allowance: float
    taxable_income: float
    income_tax: float
    national_insurance: float
    take_home: float
    marginal_rate: float            # marginal INCOME TAX rate incl. taper effect
    effective_rate: float           # (tax + NI) / gross


def calc_income_tax(
    gross: float,
    *,
    tax_year: str,
    pension_contribution: float = 0.0,
    gift_aid: float = 0.0,
) -> IncomeTaxResult:
    """Headline income tax + employee NI + take-home for an individual.

    Scope: England/Wales/NI rest-of-UK rates. Pension contributions are treated
    as reducing adjusted net income (relief-at-source / net-pay both modelled as
    a reduction to ANI for planning). Gift Aid extends the basic-rate band.
    Excludes: Scottish rates, dividend/savings-specific banding, student loan.
    """
    ty = get_tax_year(tax_year)
    gross = _n(gross)
    pension = _n(pension_contribution)
    gift_aid = _n(gift_aid)

    adjusted = max(0.0, gross - pension)
    gift_aid_gross = gift_aid / (1 - ty.basic_rate) if gift_aid > 0 else 0.0

    # Personal allowance taper: lose £1 per £2 over taper_start, on ANI.
    pa = ty.personal_allowance
    if adjusted > ty.taper_start:
        pa = max(0.0, ty.personal_allowance - (adjusted - ty.taper_start) / 2)

    taxable = max(0.0, adjusted - pa)

    # Basic-rate band width is fixed at its full-PA value (£37,700) even once
    # the taper has reduced the CURRENT pa — using the tapered `pa` here would
    # let newly-exposed income fall into the 20% band instead of 40%, which is
    # exactly wrong: the real ~60% marginal rate between £100k-£125,140 only
    # arises because that income lands in the 40% band. Extended by gift aid.
    basic_band = max(0.0, ty.basic_rate_limit - ty.personal_allowance) + gift_aid_gross
    basic = min(taxable, basic_band)
    higher_band = ty.higher_rate_limit - (ty.basic_rate_limit - ty.personal_allowance)
    higher = min(max(0.0, taxable - basic), higher_band)
    additional = max(0.0, taxable - basic - higher)

    income_tax = (
        basic * ty.basic_rate
        + higher * ty.higher_rate
        + additional * ty.additional_rate
    )

    # Employee NI (Class 1 primary).
    ni_main = max(0.0, min(adjusted, ty.ni_upper_earnings) - ty.ni_primary_threshold)
    ni_upper = max(0.0, adjusted - ty.ni_upper_earnings)
    ni = ni_main * ty.ni_main_rate + ni_upper * ty.ni_upper_rate

    # Marginal income-tax rate (captures the 60% taper zone).
    if adjusted > ty.higher_rate_limit:
        marginal = ty.additional_rate
    elif adjusted > ty.taper_start:
        marginal = 0.60  # 40% + PA withdrawal
    elif adjusted > ty.basic_rate_limit:
        marginal = ty.higher_rate
    elif adjusted > pa:
        marginal = ty.basic_rate
    else:
        marginal = 0.0

    return IncomeTaxResult(
        gross=round(gross),
        adjusted_net_income=round(adjusted),
        personal_allowance=round(pa),
        taxable_income=round(taxable),
        income_tax=round(income_tax),
        national_insurance=round(ni),
        take_home=round(adjusted - income_tax - ni),
        marginal_rate=marginal,
        effective_rate=round((income_tax + ni) / gross, 4) if gross > 0 else 0.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Child Benefit / HICBC
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChildBenefitResult:
    children: int
    annual_entitlement: float
    net_received: float             # after HICBC clawback
    charge_rate: float              # 0.0 = keep all, 1.0 = fully clawed back
    pct_retained: int


def calc_child_benefit(
    num_children: int,
    highest_earner_income: float,
    *,
    tax_year: str,
    pension_contribution: float = 0.0,
) -> ChildBenefitResult:
    """Child Benefit entitlement net of the High Income Child Benefit Charge.

    HICBC is assessed on the HIGHER earner's adjusted net income. The taper runs
    linearly from hicbc_taper_start to hicbc_taper_end; above the end the charge
    equals the full benefit.
    """
    ty = get_tax_year(tax_year)
    num_children = int(num_children or 0)
    if num_children <= 0:
        return ChildBenefitResult(0, 0.0, 0.0, 0.0, 0)

    weekly = ty.cb_weekly_first_child + ty.cb_weekly_additional_child * (num_children - 1)
    annual = round(weekly * 52)

    ani = max(0.0, _n(highest_earner_income) - _n(pension_contribution))

    if ani <= ty.hicbc_taper_start:
        return ChildBenefitResult(num_children, annual, float(annual), 0.0, 100)
    if ani >= ty.hicbc_taper_end:
        return ChildBenefitResult(num_children, annual, 0.0, 1.0, 0)

    rate = (ani - ty.hicbc_taper_start) / (ty.hicbc_taper_end - ty.hicbc_taper_start)
    net = round(annual * (1 - rate))
    return ChildBenefitResult(num_children, annual, float(net), rate, round((1 - rate) * 100))


# ─────────────────────────────────────────────────────────────────────────────
# Inheritance Tax (simplified, relationship-aware)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IHTResult:
    estate_value: float
    nil_rate_band: float
    residence_nil_rate_band: float
    total_threshold: float
    taxable_estate: float
    tax_due: float
    spouse_exemption_applied: bool


def calc_iht(
    estate_value: float,
    *,
    tax_year: str,
    is_married_or_civil_partner: bool,
    leaves_home_to_direct_descendant: bool = True,
) -> IHTResult:
    """Simplified IHT on a single estate.

    Relationship-aware by design (architecture v0.3 §6): the spouse/civil-partner
    exemption is applied RULE-BY-RULE, never via a blanket 'unmarried' flag. For
    an unmarried individual, transfers to a partner are NOT exempt and the
    transferable nil-rate band does not apply. This function models one estate;
    it does not attempt inter-partner transfer planning (deliberately — that is a
    firewall/adviser matter).
    """
    ty = get_tax_year(tax_year)
    estate = _n(estate_value)

    # Spouse exemption: unlimited transfer to spouse/CP is exempt. Modelled here
    # only as a boolean outcome flag; the actual exempt transfer is out of scope.
    if is_married_or_civil_partner:
        # A full spousal transfer would leave nothing taxable; we surface that
        # the exemption is available rather than assuming the whole estate passes.
        spouse_exemption = True
    else:
        spouse_exemption = False

    rnrb = ty.iht_residence_nil_rate_band if leaves_home_to_direct_descendant else 0
    threshold = ty.iht_nil_rate_band + rnrb
    taxable = max(0.0, estate - threshold)
    tax = taxable * ty.iht_rate

    return IHTResult(
        estate_value=round(estate),
        nil_rate_band=ty.iht_nil_rate_band,
        residence_nil_rate_band=rnrb,
        total_threshold=threshold,
        taxable_estate=round(taxable),
        tax_due=round(tax),
        spouse_exemption_applied=spouse_exemption,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SDLT additional-property surcharge
# ─────────────────────────────────────────────────────────────────────────────

def calc_sdlt_surcharge(purchase_price: float, *, tax_year: str) -> float:
    """The additional-property SDLT surcharge only (not full banded SDLT).

    This is the figure that matters for the household's keep-vs-sell decision:
    the surcharge applies to a second property, and is avoided if replacing a
    main residence. Returns the surcharge amount, not total SDLT.
    """
    ty = get_tax_year(tax_year)
    return round(_n(purchase_price) * ty.sdlt_additional_surcharge)


# ─────────────────────────────────────────────────────────────────────────────
# Projections (compound growth with monthly contributions)
# ─────────────────────────────────────────────────────────────────────────────

def project_pot(
    current_value: float,
    monthly_contribution: float,
    years: float,
    annual_growth_rate: float = 0.07,
) -> int:
    """Future value of a pot with monthly contributions at an annual growth rate.

    Growth applied monthly. Pure compound-interest projection — no tax, no
    inflation adjustment (callers handle real-terms framing).
    """
    cur = _n(current_value)
    monthly = _n(monthly_contribution)
    if years <= 0:
        return round(cur)
    r = annual_growth_rate / 12
    n = years * 12
    future = cur * (1 + r) ** n
    if monthly > 0 and r != 0:
        future += monthly * (((1 + r) ** n - 1) / r)
    elif monthly > 0:
        future += monthly * n
    return round(future)


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def age_from_dob(dob: str, on: date | None = None) -> int | None:
    """Age in whole years from an ISO date string; None if unparseable."""
    if not dob:
        return None
    try:
        d = date.fromisoformat(dob)
    except (ValueError, TypeError):
        return None
    ref = on or date.today()
    return ref.year - d.year - ((ref.month, ref.day) < (d.month, d.day))


def days_until(target: str, on: date | None = None) -> int | None:
    """Whole days until an ISO date; None if unparseable."""
    if not target:
        return None
    try:
        t = date.fromisoformat(target)
    except (ValueError, TypeError):
        return None
    return (t - (on or date.today())).days
