"""
Strategy review staleness (Stage 2 Step 4). Fixed 90-day review period
(Shannon, 1 Nov 2026) — a settings screen to change the period is
explicitly deferred, not built in Steps 1-4.
"""
from __future__ import annotations

from datetime import date

REVIEW_PERIOD_DAYS = 90


def is_strategy_stale(last_reviewed_date, *, on: date | None = None) -> bool:
    """Never reviewed, or last reviewed more than REVIEW_PERIOD_DAYS ago."""
    if last_reviewed_date is None:
        return True
    ref = on or date.today()
    if isinstance(last_reviewed_date, str):
        last_reviewed_date = date.fromisoformat(last_reviewed_date)
    return (ref - last_reviewed_date).days > REVIEW_PERIOD_DAYS
