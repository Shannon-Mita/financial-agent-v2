#!/usr/bin/env python3
"""
migrate_v1_db.py — run this ON THE DROPLET against the real database.

NON-DESTRUCTIVE: reads the old database, writes a brand new facts database.
The old file (~/financial-agent/data/financial_agent.db) is never modified or
deleted. If anything looks wrong in the report, just delete the new file and
nothing has been lost.

Usage:
    python3 migrate_v1_db.py \
        --old ~/financial-agent/data/financial_agent.db \
        --new ~/financial-agent/data/wealth_facts.db

Prints a verification report: how many facts were migrated, which fields
needed coercion, and any discrepancies found in the old data (e.g. mismatched
goals). Review the report before we wire anything live.
"""
import argparse
import json
import sqlite3
import sys
import os
from datetime import date, datetime

# Allow running this script directly (python3 scripts/migrate_v1_db.py) without
# installing the package — add the repo root (parent of scripts/) to the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from facts_layer import FactStore
from migrate import migrate_v1_profile


def load_old_profile(old_db_path: str) -> tuple[dict, date]:
    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT data, updated_at FROM profile WHERE id = 1"
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit("No profile row found in the old database (id=1). Nothing to migrate.")

    blob = json.loads(row["data"])
    try:
        as_of = datetime.fromisoformat(row["updated_at"]).date()
    except (ValueError, TypeError):
        as_of = date.today()
    return blob, as_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="Path to the existing financial_agent.db")
    ap.add_argument("--new", required=True, help="Path to create the new facts database")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the report only; do not write the new database")
    args = ap.parse_args()

    print(f"Reading old profile from {args.old} ...")
    blob, as_of = load_old_profile(args.old)
    print(f"Profile last updated: {as_of.isoformat()} (used as the freshness "
          f"baseline for every migrated fact)")

    facts, report = migrate_v1_profile(blob, as_of)

    print("\n" + "=" * 68)
    print("MIGRATION REPORT")
    print("=" * 68)
    print(report.summary())

    if args.dry_run:
        print("\n[dry run] Not writing the new database. Re-run without "
              "--dry-run once this report looks right.")
        return

    print(f"\nWriting {len(facts)} facts to {args.new} ...")
    store = FactStore(args.new)
    store.set_many(facts)
    store.close()

    # Verify: reopen and spot-check a few load-bearing keys.
    verify = FactStore(args.new)
    checks = [
        "income.shannon.paye_salary",
        "income.partner.paye_salary",
        "property.main.value",
        "property.main.mortgage_balance",
        "cashflow.emergency_savings",
    ]
    print("\n" + "=" * 68)
    print("VERIFICATION — spot-checking key facts in the new database")
    print("=" * 68)
    all_ok = True
    for key in checks:
        f = verify.get(key)
        if f is None:
            print(f"  MISSING: {key}")
            all_ok = False
        else:
            print(f"  {key} = {f.value} (as of {f.as_of})")
    verify.close()

    print("\n" + ("All required fields present." if all_ok else
                  "WARNING: some required fields are missing — do not proceed "
                  "to wiring this live until resolved."))
    print(f"\nOld database untouched at: {args.old}")
    print(f"New facts database at:     {args.new}")


if __name__ == "__main__":
    sys.exit(main())
