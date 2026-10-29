"""
Tests for the strategy graph. The behaviours that matter: the projection is
honest about the growth band (on-track vs at-risk vs off-track), assumption
breaches are detected in both directions, and opportunity scoring correctly
prefers a low-effort high-confidence lever over a high-value high-effort one.
"""
import pytest
from strategy import (
    Objective, TrackStatus, project_to_target,
    Assumption, Strategy, monitor_strategies,
    Opportunity, Complexity, score_opportunity, rank_opportunities,
)


# ─────────────────────────────────────────────────────────────────────────────
# Objective + projection
# ─────────────────────────────────────────────────────────────────────────────

def test_objective_from_fire():
    obj = Objective.from_fire(monthly_income=15000, swr_pct=4, target_years=10)
    # 15000*12 / 0.04 = 4,500,000
    assert obj.fire_number == 4500000

def test_on_track_when_central_reaches():
    obj = Objective(fire_number=100000, target_years=10)
    # £50k + £500/mo at 7% over 10y comfortably exceeds £100k
    p = project_to_target(50000, 500, obj)
    assert p.status == TrackStatus.ON_TRACK
    assert p.gap_central == 0
    assert p.required_monthly_to_close == 0

def test_off_track_when_even_optimistic_misses():
    obj = Objective(fire_number=5000000, target_years=5)
    p = project_to_target(50000, 500, obj)
    assert p.status == TrackStatus.OFF_TRACK
    assert p.gap_central > 0
    assert p.required_monthly_to_close > 0

def test_at_risk_between_bands():
    # Tune so optimistic (9%) reaches but central (7%) just misses.
    obj = Objective(fire_number=100000, target_years=10)
    # Find a contribution where central < target <= high.
    p = project_to_target(0, 560, obj)
    # 560/mo for 10y: 7% ~= 97k (miss), 9% ~= 108k (reach) -> at risk
    assert p.status == TrackStatus.AT_RISK

def test_projection_band_ordering():
    obj = Objective(fire_number=200000, target_years=15)
    p = project_to_target(20000, 400, obj)
    assert p.projected_low <= p.projected_central <= p.projected_high

def test_progress_pct():
    obj = Objective(fire_number=100000, target_years=10)
    p = project_to_target(25000, 0, obj)
    assert p.progress_pct == 25


# ─────────────────────────────────────────────────────────────────────────────
# Assumption monitoring
# ─────────────────────────────────────────────────────────────────────────────

def test_assumption_not_breached_within_range():
    a = Assumption("mortgage_rate", 3.0, 5.0, actual=4.07)
    assert a.is_breached() is False

def test_assumption_breached_above():
    a = Assumption("mortgage_rate", 3.0, 5.0, actual=6.24)
    assert a.is_breached() is True
    assert a.breach_direction() == "above"

def test_assumption_breached_below():
    a = Assumption("rental_yield", 5.0, 8.0, actual=3.0)
    assert a.is_breached() is True
    assert a.breach_direction() == "below"

def test_assumption_unknown_actual_not_breached():
    a = Assumption("growth", 5.0, 9.0, actual=None)
    assert a.is_breached() is False

def test_monitor_flags_breached_strategy():
    s = Strategy(
        id="retain_flat", title="Retain London flat and let",
        thesis="Rental + appreciation beats selling",
        assumptions=(
            Assumption("rent_pcm", 2200, 2800, actual=2500),   # ok
            Assumption("mortgage_rate", 3.0, 5.0, actual=6.24), # breached
        ),
    )
    alerts = monitor_strategies([s])
    assert len(alerts) == 1
    assert alerts[0].assumption_name == "mortgage_rate"
    assert "Re-evaluate" in alerts[0].message()

def test_monitor_clean_strategy_no_alerts():
    s = Strategy(
        id="isa_max", title="Max ISAs", thesis="Tax-free growth",
        assumptions=(Assumption("isa_allowance", 20000, 20000, actual=20000),),
    )
    assert monitor_strategies([s]) == []


# ─────────────────────────────────────────────────────────────────────────────
# Opportunity scoring
# ─────────────────────────────────────────────────────────────────────────────

def test_low_effort_high_confidence_beats_high_effort():
    obj = Objective(fire_number=4500000, target_years=10)
    easy = Opportunity("pension", "Pension top-up", annual_value_gbp=4000,
                       complexity=Complexity.LOW, confidence=0.95)
    hard = Opportunity("side_biz", "Side business", annual_value_gbp=10000,
                       complexity=Complexity.HIGH, confidence=0.5, setup_hours=200)
    ranked = rank_opportunities([hard, easy], obj)
    # Despite lower raw £, the easy high-confidence low-complexity one should win
    assert ranked[0].opportunity.id == "pension"

def test_one_off_value_amortised():
    obj = Objective(fire_number=100000, target_years=10)
    opp = Opportunity("sdlt_saving", "Avoid SDLT surcharge",
                      annual_value_gbp=0, one_off_value_gbp=22500,
                      complexity=Complexity.LOW, confidence=1.0, high_stakes=True)
    scored = score_opportunity(opp, obj)
    # 22500 / 5 = 4500 annualised
    assert scored.annualised_value == 4500

def test_confidence_scales_score():
    obj = Objective(fire_number=100000, target_years=10)
    high_conf = Opportunity("a", "A", annual_value_gbp=1000, confidence=1.0,
                            complexity=Complexity.LOW)
    low_conf = Opportunity("b", "B", annual_value_gbp=1000, confidence=0.3,
                           complexity=Complexity.LOW)
    assert score_opportunity(high_conf, obj).score > score_opportunity(low_conf, obj).score

def test_ranking_is_descending():
    obj = Objective(fire_number=100000, target_years=10)
    opps = [
        Opportunity("a", "A", annual_value_gbp=500, complexity=Complexity.LOW, confidence=1.0),
        Opportunity("b", "B", annual_value_gbp=5000, complexity=Complexity.LOW, confidence=1.0),
        Opportunity("c", "C", annual_value_gbp=2000, complexity=Complexity.LOW, confidence=1.0),
    ]
    ranked = rank_opportunities(opps, obj)
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)
