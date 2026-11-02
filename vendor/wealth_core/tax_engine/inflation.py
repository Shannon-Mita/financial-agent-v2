"""
OBR CPI forecast and inflation adjustment (spec §2/§8: both 2030-money goal
targets are deflated to today's money for comparison against today's-money
entered figures — never the reverse, which would be a growth projection and
out of scope for this maths-only layer).

CPI_FORECAST is calendar-year, year-on-year % growth, not tax-year — this
matches the OBR's own published axis and the household's goal dates
(calendar dates like 5 Oct 2030), not the 6 April-5 April tax year.

MAINTENANCE: replace a year's forecast figure with the ONS actual once that
calendar year's outturn is published (ONS Consumer Prices Index bulletin),
and add new forecast years as the OBR publishes further out. Never guess,
never carry forward a stale figure — fetch and re-verify.

Verified against the OBR, fetched 2026-11-02:
  https://obr.uk/efo/economic-and-fiscal-outlook-october-2026/
  "October 2026 Economic and fiscal outlook - detailed forecast tables:
  economy", Table 1.7 Inflation, column E (CPI, year-on-year growth,
  calendar year basis), published 28 Oct 2026. CPI and CPIH inflation are
  based on outturn data up to and including July 2026.
"""

CPI_FORECAST = {
    2026: 0.031127927115832454,
    2027: 0.034212869693871939,
    2028: 0.020986006416478409,
    2029: 0.021046172676413510,
    2030: 0.020101263737405173,
}


class InflationYearNotAvailable(Exception):
    """Raised when a calculation needs a CPI figure for a year not on file —
    fetch and add it rather than guessing or extrapolating."""


def deflate_to_today_money(amount: float, *, nominal_year: int, today_year: int) -> float:
    """Convert `amount`, expressed in `nominal_year` money, into
    `today_year` money, by dividing out the cumulative forecast CPI growth
    between the two years.

    `today_year` is the actual current calendar year, supplied by the
    caller — this function is pure and never reads a real-time clock.
    Deflates FUTURE money back to today's money only (`nominal_year` must
    be >= `today_year`); it never inflates a figure forward, which would be
    a growth projection, not a unit conversion.

    Compounding convention: CPI_FORECAST[Y] is the growth that occurred
    DURING year Y, so converting `nominal_year` money to `today_year` money
    divides out every year strictly after `today_year` up to and including
    `nominal_year`.
    """
    if nominal_year < today_year:
        raise ValueError(
            f"nominal_year ({nominal_year}) must be >= today_year ({today_year}) — "
            f"this function deflates future money to today's money, never the reverse."
        )
    if nominal_year == today_year:
        return amount
    factor = 1.0
    for year in range(today_year + 1, nominal_year + 1):
        if year not in CPI_FORECAST:
            raise InflationYearNotAvailable(
                f"No CPI figure on file for {year}. Fetch the OBR forecast (or ONS "
                f"actual, if published) and add it to CPI_FORECAST before using it."
            )
        factor *= 1 + CPI_FORECAST[year]
    return amount / factor
