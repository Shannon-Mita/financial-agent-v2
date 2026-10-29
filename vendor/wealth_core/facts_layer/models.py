"""
Typed household facts (architecture v0.3, Layer 1).

Replaces the single mutable JSON profile blob with typed, timestamped, sourced
facts. Two properties this buys us that the blob could not:

  1. Freshness — every fact knows when it was last confirmed true, so downstream
     features can refuse to advise on stale data (the freshness gate).
  2. History / audit — writes are append-only, so we can answer "what did we
     believe the mortgage balance was on 1 July?" — required for reproducing any
     past recommendation.

A fact is identified by a dotted key (e.g. "income.shannon.paye_salary"). The
UI keeps a convenient profile projection (see store.project()), but the facts
are the source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum


class Source(str, Enum):
    """Where a fact came from. Kept distinct so we never conflate what the user
    told us with what we derived or fetched — the reviewers flagged mixing these
    in one JSON structure as a core weakness."""
    USER_STATED = "user_stated"   # the household told us directly
    DERIVED = "derived"           # computed by our own deterministic code
    EXTERNAL = "external"         # fetched from an outside source (with evidence)


class Unit(str, Enum):
    GBP = "GBP"                   # a money amount
    GBP_PER_YEAR = "GBP/year"
    GBP_PER_MONTH = "GBP/month"
    PERCENT = "percent"
    DATE = "date"                 # ISO date string in value
    BOOL = "bool"
    COUNT = "count"
    TEXT = "text"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Fact:
    """A single typed fact about the household, valid as of a point in time.

    `as_of` is when the value was last confirmed true by its source (this drives
    freshness). `entered_at` is when we recorded it (this drives history order).
    They differ: a user might confirm on 1 March a salary that took effect in
    January; as_of=March is what freshness cares about.
    """
    key: str
    value: object                 # number | str | bool
    unit: Unit
    source: Source
    category: str                 # coarse grouping: income, property, pension, ...
    as_of: date                   # last confirmed true
    entered_at: datetime          # when we recorded this row
    note: str = ""

    def __post_init__(self):
        if not self.key or "." not in self.key:
            raise ValueError(f"Fact key must be dotted, got: {self.key!r}")

    @staticmethod
    def create(
        key: str,
        value: object,
        unit: Unit,
        source: Source,
        category: str,
        as_of: date | None = None,
        note: str = "",
    ) -> "Fact":
        return Fact(
            key=key,
            value=value,
            unit=unit,
            source=source,
            category=category,
            as_of=as_of or date.today(),
            entered_at=_utcnow(),
            note=note,
        )

    def age_days(self, on: date | None = None) -> int:
        """How many days since this fact was last confirmed true."""
        return ((on or date.today()) - self.as_of).days
