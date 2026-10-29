"""
Freshness policy + gate (architecture v0.3, §7 and Layer 4).

The reviewers were unanimous that data staleness must be a HARD GATE, not a
nudge: if a required input is older than its policy, the system refuses to
generate advice and asks for a refresh instead. This module encodes the policy
(as concrete numbers, not vibes) and provides the gate that features call before
they compute anything user-facing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import Fact


# Per-category maximum age in days before a fact is "stale".
# Values from architecture v0.3 §7 — starting points, tunable with real usage.
DEFAULT_FRESHNESS_DAYS: dict[str, int] = {
    "balance": 30,        # investment / cash balances move
    "mortgage": 30,       # balance changes monthly
    "income": 90,         # salary is stable-ish
    "spending": 60,
    "valuation": 180,     # property valuations move slowly
    "pension": 90,
    "protection": 365,    # policies rarely change
    "goal": 365,          # goals are deliberately sticky
    "profile": 365,       # DOBs, names, relationship status
}

# Fall-back if a category has no explicit policy.
FALLBACK_FRESHNESS_DAYS = 90


def max_age_for(category: str, policy: dict[str, int] | None = None) -> int:
    p = policy or DEFAULT_FRESHNESS_DAYS
    return p.get(category, FALLBACK_FRESHNESS_DAYS)


@dataclass(frozen=True)
class StaleFact:
    key: str
    category: str
    age_days: int
    max_age_days: int


@dataclass(frozen=True)
class FreshnessResult:
    """Outcome of a gate check. `ok` is the thing callers branch on."""
    ok: bool
    stale: tuple[StaleFact, ...]
    missing: tuple[str, ...]      # required keys with no fact at all

    def block_reason(self) -> str:
        """Human-readable reason a feature is blocked, for the refusal message."""
        parts = []
        if self.missing:
            parts.append(
                "missing: " + ", ".join(sorted(self.missing))
            )
        if self.stale:
            worst = sorted(self.stale, key=lambda s: -s.age_days)
            parts.append(
                "stale: " + ", ".join(
                    f"{s.key} ({s.age_days}d old, max {s.max_age_days}d)"
                    for s in worst
                )
            )
        return "; ".join(parts) if parts else "ok"


def check_freshness(
    facts: dict[str, Fact],
    required_keys: list[str],
    *,
    on: date | None = None,
    policy: dict[str, int] | None = None,
) -> FreshnessResult:
    """Gate: are all required facts present AND fresh enough to advise on?

    `facts` is the current fact set keyed by fact key (as from store.current()).
    `required_keys` is what the calling feature needs. Returns ok=False with the
    specific stale/missing keys so the caller can ask the user to refresh exactly
    those, rather than a vague "update your profile".
    """
    ref = on or date.today()
    stale: list[StaleFact] = []
    missing: list[str] = []

    for key in required_keys:
        fact = facts.get(key)
        if fact is None:
            missing.append(key)
            continue
        limit = max_age_for(fact.category, policy)
        age = fact.age_days(ref)
        if age > limit:
            stale.append(StaleFact(key, fact.category, age, limit))

    return FreshnessResult(
        ok=(not stale and not missing),
        stale=tuple(stale),
        missing=tuple(missing),
    )
