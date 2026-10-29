"""
Strategy graph (architecture v0.3, §4 and §5).

Two jobs:

1. Strategies are stored as ASSUMPTIONS. Layer 4 watches the assumptions and
   flags "assumption X has moved out of its expected range -> re-evaluate
   strategy Y" — rather than regenerating prose every quarter. This is what
   makes strategy-maintenance deterministic and trustworthy.

2. Opportunities are SCORED AGAINST THE OBJECTIVE, not by raw £. An opportunity
   worth £10k/yr that needs 15 hours/week may be worse than one worth £4k/yr
   that needs a one-off afternoon. Scoring makes "does this actually improve our
   wealth trajectory?" the question, not "is this financially interesting?"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ─────────────────────────────────────────────────────────────────────────────
# Assumptions and strategies
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Assumption:
    """A named value a strategy depends on, with the range within which the
    strategy still holds. If the actual value leaves the range, the strategy
    needs re-evaluation."""
    name: str
    expected_min: float
    expected_max: float
    actual: float | None = None    # latest observed value, if known
    unit: str = ""

    def is_breached(self) -> bool:
        if self.actual is None:
            return False
        return self.actual < self.expected_min or self.actual > self.expected_max

    def breach_direction(self) -> str:
        if self.actual is None:
            return ""
        if self.actual < self.expected_min:
            return "below"
        if self.actual > self.expected_max:
            return "above"
        return ""


@dataclass(frozen=True)
class Strategy:
    """A named approach that contributes to the objective, resting on
    assumptions and linked to concrete levers."""
    id: str
    title: str
    thesis: str
    assumptions: tuple[Assumption, ...] = field(default_factory=tuple)
    lever_ids: tuple[str, ...] = field(default_factory=tuple)

    def breached_assumptions(self) -> list[Assumption]:
        return [a for a in self.assumptions if a.is_breached()]


@dataclass(frozen=True)
class AssumptionAlert:
    strategy_id: str
    strategy_title: str
    assumption_name: str
    expected_min: float
    expected_max: float
    actual: float
    direction: str

    def message(self) -> str:
        return (
            f"Strategy '{self.strategy_title}': assumption '{self.assumption_name}' "
            f"is {self.direction} its expected range "
            f"({self.expected_min}–{self.expected_max}); now {self.actual}. "
            f"Re-evaluate."
        )


def monitor_strategies(strategies: list[Strategy]) -> list[AssumptionAlert]:
    """Return an alert for every breached assumption across all strategies.

    This is the deterministic 'strategy maintenance' loop: no LLM, no prose
    regeneration — just 'this assumption moved, look again'.
    """
    alerts: list[AssumptionAlert] = []
    for s in strategies:
        for a in s.breached_assumptions():
            alerts.append(AssumptionAlert(
                strategy_id=s.id, strategy_title=s.title,
                assumption_name=a.name,
                expected_min=a.expected_min, expected_max=a.expected_max,
                actual=a.actual, direction=a.breach_direction(),
            ))
    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# Opportunity scoring against the objective
# ─────────────────────────────────────────────────────────────────────────────

class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_COMPLEXITY_WEIGHT = {Complexity.LOW: 1.0, Complexity.MEDIUM: 0.6, Complexity.HIGH: 0.3}


@dataclass(frozen=True)
class Opportunity:
    """A candidate action, whatever its source. Scored, never auto-recommended
    for high-stakes categories."""
    id: str
    title: str
    annual_value_gbp: float
    one_off_value_gbp: float = 0.0
    complexity: Complexity = Complexity.MEDIUM
    confidence: float = 0.7            # 0..1, from the qualification firewall
    strategy_id: str | None = None     # which strategy it advances
    high_stakes: bool = False          # CGT/SDLT/IHT -> never auto-actioned
    setup_hours: float = 0.0


@dataclass(frozen=True)
class ScoredOpportunity:
    opportunity: Opportunity
    score: float
    annualised_value: float


def score_opportunity(opp: Opportunity, objective: Objective) -> ScoredOpportunity:
    """Score an opportunity by its contribution to the goal, adjusted for
    confidence and complexity. Deliberately simple and transparent — the point
    is to rank, not to produce a spurious precise number.

    annualised value = annual + a 5-year amortisation of any one-off value.
    score = annualised_value x confidence x complexity_weight
    """
    annualised = opp.annual_value_gbp + (opp.one_off_value_gbp / 5.0)
    weight = _COMPLEXITY_WEIGHT[opp.complexity]
    score = annualised * max(0.0, min(1.0, opp.confidence)) * weight
    return ScoredOpportunity(
        opportunity=opp,
        score=round(score),
        annualised_value=round(annualised),
    )


def rank_opportunities(opps: list[Opportunity], objective: Objective) -> list[ScoredOpportunity]:
    """Score and rank; high-stakes items are kept but flagged, never dropped."""
    scored = [score_opportunity(o, objective) for o in opps]
    scored.sort(key=lambda s: -s.score)
    return scored
