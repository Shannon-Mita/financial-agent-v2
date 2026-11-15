"""
Strategy review staleness (Stage 2 Step 4). Fixed 90-day review period
(Shannon, 1 Nov 2026) — a settings screen to change the period is
explicitly deferred, not built in Steps 1-4.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

REVIEW_PERIOD_DAYS = 90

LONDON_TZ = ZoneInfo("Europe/London")


def is_strategy_stale(last_reviewed_date, *, on: date | None = None) -> bool:
    """Never reviewed, or last reviewed more than REVIEW_PERIOD_DAYS ago."""
    if last_reviewed_date is None:
        return True
    ref = on or date.today()
    if isinstance(last_reviewed_date, str):
        last_reviewed_date = date.fromisoformat(last_reviewed_date)
    return (ref - last_reviewed_date).days > REVIEW_PERIOD_DAYS


def today_in_london(now: datetime | None = None) -> date:
    """Today's date in Europe/London, DST-aware. A strategy created near
    midnight UTC in summer (BST = UTC+1) must get the date the user
    actually experiences, not the server's UTC date — plain date.today()
    on a UTC server would get this wrong for part of the year. `now`
    (tz-aware) is injectable for tests; defaults to the real current time."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.astimezone(LONDON_TZ).date()
