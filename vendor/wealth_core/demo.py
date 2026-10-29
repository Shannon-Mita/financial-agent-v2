"""
demo.py — see the whole Phase 0 + Phase 1 stack working end to end.

Run:  python demo.py

It seeds a fact store with the household's real numbers, runs the deterministic
monthly recap through the freshness gate, then demonstrates the stale-data
refusal and the audit/history capability. No network, no LLM.
"""
from datetime import date, timedelta

from facts_layer import FactStore, Fact, Unit, Source
from tax_engine import calc_income_tax, calc_child_benefit, calc_iht
from recap import build_recap
from ops import smoke_test
from strategy import (
    Objective, project_to_target, Strategy, Assumption, monitor_strategies,
    Opportunity, Complexity, rank_opportunities,
)
from delivery import render_recap_telegram, deliver_recap, FakeSender


def seed_household(store, as_of):
    facts = [
        ("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
        ("income.partner.paye_salary", 100000, Unit.GBP_PER_YEAR, "income"),
        ("property.main.value", 495000, Unit.GBP, "valuation"),
        ("property.main.mortgage_balance", 375000, Unit.GBP, "mortgage"),
        ("property.main.fixed_rate_end", "2027-09-30", Unit.DATE, "mortgage"),
        ("cashflow.emergency_savings", 13000, Unit.GBP, "balance"),
        ("cashflow.monthly_essentials", 3500, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_lifestyle", 2000, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_childcare", 0, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_other", 1200, Unit.GBP_PER_MONTH, "spending"),
    ]
    for key, val, unit, cat in facts:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat, as_of=as_of))


def main():
    print("=" * 68)
    print("DEPLOY SMOKE TEST")
    print("=" * 68)
    print(smoke_test(":memory:").summary())

    print("\n" + "=" * 68)
    print("TAX ENGINE — household headline positions (2025/26)")
    print("=" * 68)
    s = calc_income_tax(55000, tax_year="2025/26")
    p = calc_income_tax(100000, tax_year="2025/26")
    print(f"Shannon £55k: tax £{s.income_tax:,}  NI £{s.national_insurance:,}  "
          f"take-home £{s.take_home:,}  (marginal {int(s.marginal_rate*100)}%)")
    print(f"Partner £100k: PA £{p.personal_allowance:,}  take-home £{p.take_home:,}  "
          f"(marginal {int(p.marginal_rate*100)}%)")
    cb = calc_child_benefit(1, 100000, tax_year="2025/26")
    print(f"Child Benefit (1 child, £100k earner): net £{cb.net_received:,.0f} "
          f"of £{cb.annual_entitlement:,.0f} — {cb.pct_retained}% retained")
    iht = calc_iht(600000, tax_year="2025/26", is_married_or_civil_partner=False)
    print(f"IHT on £600k estate, unmarried: £{iht.tax_due:,} due "
          f"(spouse exemption available: {iht.spouse_exemption_applied})")

    print("\n" + "=" * 68)
    print("MONTHLY RECAP — fresh data")
    print("=" * 68)
    store = FactStore()
    seed_household(store, as_of=date.today() - timedelta(days=10))
    recap = build_recap(store, num_children=1)
    print(recap.to_text())

    print("\n" + "=" * 68)
    print("MONTHLY RECAP — stale data (freshness gate refuses)")
    print("=" * 68)
    stale_store = FactStore()
    seed_household(stale_store, as_of=date.today() - timedelta(days=200))
    print(build_recap(stale_store, num_children=1).to_text())

    print("\n" + "=" * 68)
    print("AUDIT — mortgage balance history (append-only)")
    print("=" * 68)
    store.set(Fact.create("property.main.mortgage_balance", 372000,
                          Unit.GBP, Source.USER_STATED, "mortgage"))
    for f in store.history("property.main.mortgage_balance"):
        print(f"  as_of {f.as_of}  ->  £{f.value:,}")

    print("\n" + "=" * 68)
    print("STRATEGY GRAPH — assumption monitoring (deterministic)")
    print("=" * 68)
    retain = Strategy(
        id="retain_flat", title="Retain London flat and let",
        thesis="Rental income + appreciation beats selling and redeploying.",
        assumptions=(
            Assumption("rent_pcm", 2200, 2800, actual=2500, unit="GBP/mo"),
            Assumption("mortgage_rate", 3.0, 5.0, actual=6.24, unit="%"),  # breached
            Assumption("capital_growth", 2.0, 5.0, actual=0.5, unit="%"),  # breached
        ),
    )
    alerts = monitor_strategies([retain])
    if not alerts:
        print("  All strategy assumptions holding.")
    for a in alerts:
        print(f"  ⚠ {a.message()}")

    print("\n" + "=" * 68)
    print("OPPORTUNITY SCORING — against the goal, not raw £")
    print("=" * 68)
    obj = Objective.from_fire(monthly_income=15000, swr_pct=4, target_years=10)
    opps = [
        Opportunity("pension_taper", "Partner pension to unwind 60% trap",
                    annual_value_gbp=6000, complexity=Complexity.LOW, confidence=0.95),
        Opportunity("side_biz", "Build a side business",
                    annual_value_gbp=12000, complexity=Complexity.HIGH,
                    confidence=0.4, setup_hours=300),
        Opportunity("isa_max", "Max both ISAs before 5 April",
                    annual_value_gbp=1400, complexity=Complexity.LOW, confidence=0.9),
    ]
    for s in rank_opportunities(opps, obj):
        o = s.opportunity
        print(f"  score {s.score:>6}  | {o.title}  "
              f"(£{o.annual_value_gbp:,}/yr, {o.complexity.value} effort, "
              f"conf {int(o.confidence*100)}%)")

    print("\n" + "=" * 68)
    print("DELIVERY — the Telegram message that would be sent")
    print("=" * 68)
    sender = FakeSender()
    recap_for_delivery = build_recap(store, num_children=1)
    deliver_recap(recap_for_delivery, sender)
    print(sender.sent[0])


if __name__ == "__main__":
    main()
