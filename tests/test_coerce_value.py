"""
Pure unit tests for app.routes._coerce_value's GBP branch. Money must
accept pounds AND pence — not whole pounds only — plus a leading £, stray
spaces, and thousands commas a human would naturally type. No DB needed.
"""
import math

import pytest

from app.routes import _coerce_value
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Unit  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("381150.09", 381150.09),
    ("£381,150.09", 381150.09),
    ("381,150", 381150.0),
    ("13000", 13000.0),
    (" 22000 ", 22000.0),
])
def test_gbp_accepts_pounds_and_pence(raw, expected):
    value = _coerce_value(Unit.GBP, raw)
    assert value == pytest.approx(expected)
    assert round(value, 2) == value  # stored rounded to 2dp, never more precise


@pytest.mark.parametrize("raw", ["abc", "", "-5", "nan", "inf", "infinity", "-inf"])
def test_gbp_rejects_invalid_values(raw):
    with pytest.raises((ValueError, TypeError)):
        _coerce_value(Unit.GBP, raw)


def test_gbp_rounds_to_two_decimal_places_not_whole_pounds():
    # The whole point of this fix: 381150.09 must stay 381150.09, not get
    # rounded away to 381150.
    assert _coerce_value(Unit.GBP, "381150.09") == 381150.09
    assert _coerce_value(Unit.GBP, "381150.091") == 381150.09  # rounds to 2dp
    assert _coerce_value(Unit.GBP, "381150.006") == 381150.01  # rounds, doesn't truncate


def test_gbp_never_returns_nan_or_inf_or_negative():
    for raw in ["nan", "inf", "-inf", "-5", "-0.01"]:
        try:
            value = _coerce_value(Unit.GBP, raw)
        except (ValueError, TypeError):
            continue
        assert math.isfinite(value)
        assert value >= 0


def test_count_still_requires_a_plain_integer_unaffected_by_the_gbp_fix():
    assert _coerce_value(Unit.COUNT, "4") == 4
    assert isinstance(_coerce_value(Unit.COUNT, "4"), int)
    with pytest.raises(ValueError):
        _coerce_value(Unit.COUNT, "4.5")
