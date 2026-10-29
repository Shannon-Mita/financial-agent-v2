#!/usr/bin/env python3
"""
confirm_facts.py — interactively confirm or update the household's key facts.

This is the stopgap "update your numbers" tool until the live Flask app is
migrated to write through the facts layer directly. It walks through the
handful of facts the recap actually depends on, shows the current value and its
age, and lets you either confirm it's still accurate (press Enter — this
re-stamps as_of to today, since "still true" IS new information) or type a
replacement value (also stamped today).

Usage:
    python3 confirm_facts.py --db ~/financial-agent/data/wealth_facts.db
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from facts_layer import FactStore, Fact, Unit, Source
from recap import build_recap


# (key, human label, allow_blank_to_confirm)
FIELDS = [
    ("income.shannon.paye_salary", "Shannon's PAYE salary (£/yr)"),
    ("income.partner.paye_salary", "Partner's PAYE salary (£/yr)"),
    ("property.main.value", "Property estimated value (£)"),
    ("property.main.mortgage_balance", "Mortgage balance outstanding (£)"),
    ("property.main.fixed_rate_end", "Mortgage fixed-rate end date (YYYY-MM-DD)"),
    ("cashflow.emergency_savings", "Emergency/cash savings (£)"),
    ("cashflow.monthly_essentials", "Monthly essential spending (£)"),
    ("cashflow.monthly_lifestyle", "Monthly lifestyle spending (£)"),
    ("cashflow.monthly_childcare", "Monthly childcare spending (£)"),
    ("cashflow.monthly_other", "Monthly other spending (£)"),
    ("pensions.shannon.monthly_employee", "Shannon's monthly pension contribution (£)"),
    ("pensions.partner.monthly_employee", "Partner's monthly pension contribution (£)"),
]


def _parse(raw: str, unit: Unit):
    if unit == Unit.DATE or unit == Unit.TEXT:
        return raw
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"'{raw}' doesn't look like a number")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args()

    store = FactStore(args.db)
    today = date.today()
    changed, confirmed = [], []

    print("Confirm each figure — press Enter to keep it (stamps it fresh as of "
          "today), or type a new value.\n")

    for key, label in FIELDS:
        existing = store.get(key)
        if existing is None:
            print(f"{label}: no value on file. ", end="")
            raw = input("Enter a value (or leave blank to skip): ").strip()
            if not raw:
                print("  skipped.\n")
                continue
            unit = Unit.DATE if "date" in label.lower() else Unit.GBP
            value = _parse(raw, unit)
            store.set(Fact.create(key, value, unit, Source.USER_STATED,
                                  _category_for(key), as_of=today))
            changed.append((key, None, value))
            continue

        age = existing.age_days(today)
        current_display = existing.value
        raw = input(f"{label} = {current_display}  ({age}d old)  "
                    f"[Enter to confirm / new value]: ").strip()
        if not raw:
            # Still true — that IS new information, so re-stamp as_of.
            store.set(Fact(
                key=existing.key, value=existing.value, unit=existing.unit,
                source=existing.source, category=existing.category,
                as_of=today, entered_at=existing.entered_at.__class__.now(
                    existing.entered_at.tzinfo),
                note="reconfirmed unchanged",
            ))
            confirmed.append(key)
        else:
            try:
                value = _parse(raw, existing.unit)
            except ValueError as e:
                print(f"  Skipping — {e}")
                continue
            store.set(Fact.create(key, value, existing.unit, Source.USER_STATED,
                                  existing.category, as_of=today,
                                  note="updated by household"))
            changed.append((key, current_display, value))

    print("\n" + "=" * 60)
    print(f"Confirmed unchanged: {len(confirmed)}")
    print(f"Updated: {len(changed)}")
    for key, old, new in changed:
        print(f"  {key}: {old} -> {new}")

    store.close()

    print("\nRe-running the recap with fresh data...\n")
    store2 = FactStore(args.db)
    recap = build_recap(store2, num_children=1)
    print(recap.to_text())


def _category_for(key: str) -> str:
    if "income" in key:
        return "income"
    if "mortgage" in key or "fixed_rate_end" in key:
        return "mortgage"
    if "pension" in key:
        return "pension"
    if "emergency_savings" in key:
        return "balance"
    if "value" in key and "property" in key:
        return "valuation"
    if key.startswith("cashflow.monthly_"):
        return "spending"
    return "profile"


if __name__ == "__main__":
    main()
