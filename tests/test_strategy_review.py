"""
Pure unit tests for app/strategy_review.py — the fixed 90-day staleness
rule (Shannon, 1 Nov 2026: a settings screen to change the period is
explicitly deferred, not built in Steps 1-4).
"""
from datetime import date, timedelta

from app.strategy_review import REVIEW_PERIOD_DAYS, is_strategy_stale

TODAY = date(2026, 11, 3)


def test_never_reviewed_is_stale():
    assert is_strategy_stale(None, on=TODAY) is True


def test_reviewed_today_is_not_stale():
    assert is_strategy_stale(TODAY, on=TODAY) is False


def test_reviewed_89_days_ago_is_not_stale():
    assert is_strategy_stale(TODAY - timedelta(days=89), on=TODAY) is False


def test_reviewed_exactly_90_days_ago_is_not_stale():
    assert is_strategy_stale(TODAY - timedelta(days=REVIEW_PERIOD_DAYS), on=TODAY) is False


def test_reviewed_91_days_ago_is_stale():
    assert is_strategy_stale(TODAY - timedelta(days=91), on=TODAY) is True


def test_accepts_an_iso_date_string_too():
    old = (TODAY - timedelta(days=200)).isoformat()
    assert is_strategy_stale(old, on=TODAY) is True
