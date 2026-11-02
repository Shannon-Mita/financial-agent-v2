"""UK personal-tax calculation engine — deterministic, versioned, tested."""
from .facts import get_tax_year, TAX_YEARS, DEFAULT_TAX_YEAR, UnknownTaxYear
from .engine import (
    calc_income_tax,
    calc_child_benefit,
    calc_iht,
    calc_sdlt_surcharge,
    project_pot,
    age_from_dob,
    days_until,
)
from .childcare_policy import ChildcareEligibility
from .childcare_policy import CURRENT as CURRENT_CHILDCARE_POLICY
from .inflation import CPI_FORECAST, InflationYearNotAvailable, deflate_to_today_money

__all__ = [
    "get_tax_year", "TAX_YEARS", "DEFAULT_TAX_YEAR", "UnknownTaxYear",
    "calc_income_tax", "calc_child_benefit", "calc_iht",
    "calc_sdlt_surcharge", "project_pot", "age_from_dob", "days_until",
    "ChildcareEligibility", "CURRENT_CHILDCARE_POLICY",
    "CPI_FORECAST", "InflationYearNotAvailable", "deflate_to_today_money",
]
