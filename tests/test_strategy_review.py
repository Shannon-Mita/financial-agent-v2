"""
Pure unit tests for app/strategy_review.py — the fixed 90-day staleness
rule (Shannon, 1 Nov 2026: a settings screen to change the period is
explicitly deferred, not built in Steps 1-4) and today_in_london() (a
strategy's creation date must be the date the user actually experiences,
not the server's UTC date).
"""
from datetime import date, datetime, timedelta, timezone

from app.strategy_review import REVIEW_PERIOD_DAYS, is_strategy_stale, today_in_london

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


# ── today_in_london ──────────────────────────────────────────────────────

def test_today_in_london_matches_utc_date_in_winter_gmt():
    # GMT (UTC+0) in November — same calendar date as UTC.
    now = datetime(2026, 11, 15, 22, 0, tzinfo=timezone.utc)
    assert today_in_london(now) == date(2026, 11, 15)


def test_today_in_london_rolls_over_near_midnight_in_summer_bst():
    # BST (UTC+1) in June — 23:30 UTC is already past midnight locally,
    # so the London date is a day ahead of the UTC date. This is the
    # whole reason this helper exists rather than plain date.today().
    now = datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc)
    assert today_in_london(now) == date(2026, 6, 16)


def test_today_in_london_defaults_to_the_real_current_time():
    result = today_in_london()
    assert isinstance(result, date)
