"""
Wealth objective (architecture v0.3, §4).

Makes the goal machine-readable so opportunities can be scored against it. The
objective is NOT "maximise net worth" — it is closer to "maximise the
probability of hitting the FIRE target by the target date, subject to
constraints."

Honesty about uncertainty: we do NOT emit a spurious precise probability
("82.3%"). A deterministic point projection with optimistic/pessimistic bands is
more defensible and matches the "don't fake precision" principle the reviewers
pushed. Status is ON_TRACK / AT_RISK / OFF_TRACK based on where the target falls
relative to the band.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tax_engine import project_pot


class TrackStatus(str, Enum):
    ON_TRACK = "on_track"      # central projection reaches target
    AT_RISK = "at_risk"        # optimistic reaches, central misses
    OFF_TRACK = "off_track"    # even optimistic misses


# Growth-rate band for projections (annual, nominal).
CENTRAL_GROWTH = 0.07
PESSIMISTIC_GROWTH = 0.04
OPTIMISTIC_GROWTH = 0.09


@dataclass(frozen=True)
class Objective:
    """The household's primary wealth goal, machine-readable."""
    fire_number: float          # assets needed to sustain target spend at SWR
    target_years: float         # years from now to the target date
    # Constraints (used later to score/penalise opportunities, not to project).
    min_liquidity_gbp: float = 0.0
    max_workload_hours_week: float = 0.0
    risk_tolerance: str = "medium"   # low | medium | high

    @staticmethod
    def from_fire(monthly_income: float, swr_pct: float, target_years: float,
                  **constraints) -> "Objective":
        fire_number = (monthly_income * 12) / (swr_pct / 100)
        return Objective(fire_number=fire_number, target_years=target_years,
                         **constraints)


@dataclass(frozen=True)
class Projection:
    status: TrackStatus
    fire_number: float
    projected_central: float
    projected_low: float
    projected_high: float
    gap_central: float                 # >0 means short at central growth
    required_monthly_to_close: float   # extra monthly needed at central growth
    progress_pct: int                  # today's assets / fire_number


def project_to_target(
    current_accessible: float,
    monthly_surplus: float,
    objective: Objective,
) -> Projection:
    """Project accessible assets to the target date under three growth rates.

    'Accessible' = assets usable before pension age (ISA, GIA, cash, property
    equity if intended for the plan). Pension pots are handled separately since
    they're locked; this projection is about the FIRE bridge.
    """
    yrs = objective.target_years
    cur = max(0.0, current_accessible)
    surplus = max(0.0, monthly_surplus)

    central = project_pot(cur, surplus, yrs, CENTRAL_GROWTH)
    low = project_pot(cur, surplus, yrs, PESSIMISTIC_GROWTH)
    high = project_pot(cur, surplus, yrs, OPTIMISTIC_GROWTH)

    target = objective.fire_number
    if central >= target:
        status = TrackStatus.ON_TRACK
    elif high >= target:
        status = TrackStatus.AT_RISK
    else:
        status = TrackStatus.OFF_TRACK

    gap = max(0.0, target - central)

    # Extra monthly contribution needed to close the central gap by the target.
    required_extra = 0.0
    if gap > 0 and yrs > 0:
        r = CENTRAL_GROWTH / 12
        n = yrs * 12
        if r != 0:
            required_extra = gap * r / ((1 + r) ** n - 1)
        else:
            required_extra = gap / n

    progress = min(100, round(cur / target * 100)) if target > 0 else 0

    return Projection(
        status=status,
        fire_number=round(target),
        projected_central=central,
        projected_low=low,
        projected_high=high,
        gap_central=round(gap),
        required_monthly_to_close=round(required_extra),
        progress_pct=progress,
    )
