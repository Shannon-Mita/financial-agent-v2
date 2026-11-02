"""
Tests for adjust_for_inflation / deflate_to_today_money.

Per spec (Shannon, 1 Nov 2026): both goal targets are in 2030 money; they
are deflated to today's money for comparison against today's-money entered
figures — never the reverse (projecting entered figures forward would be a
growth projection, out of scope for this maths-only layer).

CPI_FORECAST verified against the OBR, fetched 2026-11-02:
  https://obr.uk/efo/economic-and-fiscal-outlook-october-2026/
  "October 2026 Economic and fiscal outlook – detailed forecast tables:
  economy", Table 1.7 Inflation, column E (CPI, year-on-year growth,
  calendar year basis), published 28 Oct 2026:
    2026: 3.11%, 2027: 3.42%, 2028: 2.10%, 2029: 2.10%, 2030: 2.01%.
"""
import pytest
from tax_engine.inflation import CPI_FORECAST, InflationYearNotAvailable, deflate_to_today_money


def test_same_year_is_unchanged():
    assert deflate_to_today_money(1000, nominal_year=2026, today_year=2026) == 1000


def test_deflating_future_money_reduces_the_amount():
    """£1,000 of 2030 money is worth less than £1,000 in 2026 money (prices
    rose in between) — deflating must reduce the figure, not inflate it."""
    result = deflate_to_today_money(1000, nominal_year=2030, today_year=2026)
    assert result < 1000


def test_cumulative_compounding_matches_hand_calculation():
    """£1,000 in 2030 money, deflated to 2026 money, divides out the
    compounded growth of 2027-2030 (the years BETWEEN today and the target
    year, inclusive of the target year) — not 2026-2029."""
    factor = 1.0
    for year in (2027, 2028, 2029, 2030):
        factor *= (1 + CPI_FORECAST[year])
    expected = 1000 / factor
    assert deflate_to_today_money(1000, nominal_year=2030, today_year=2026) == pytest.approx(expected)


def test_raises_if_nominal_year_before_today_year():
    """This function deflates FUTURE money to today's money, never the
    reverse — inflating a past/today figure forward is a growth
    projection, explicitly out of scope."""
    with pytest.raises(ValueError):
        deflate_to_today_money(1000, nominal_year=2024, today_year=2026)


def test_raises_for_a_year_not_on_file():
    with pytest.raises(InflationYearNotAvailable):
        deflate_to_today_money(1000, nominal_year=2032, today_year=2026)


def test_cpi_forecast_has_the_fetched_obr_figures():
    assert CPI_FORECAST[2026] == pytest.approx(0.0311, abs=1e-4)
    assert CPI_FORECAST[2027] == pytest.approx(0.0342, abs=1e-4)
    assert CPI_FORECAST[2028] == pytest.approx(0.0210, abs=1e-4)
    assert CPI_FORECAST[2029] == pytest.approx(0.0210, abs=1e-4)
    assert CPI_FORECAST[2030] == pytest.approx(0.0201, abs=1e-4)
