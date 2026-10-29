#!/usr/bin/env python3
"""
Load the facts in a wealth-core-migrated sqlite file (the output of
vendor/wealth_core/scripts/migrate_v1_db.py) into the hosted Postgres facts
table, as placeholder facts with their ORIGINAL as_of date preserved — so the
freshness gate flags every one of them for confirmation on first login, per
build spec §4.

This does NOT read the old droplet app's database directly. Run wealth-core's
own migration first:

    python3 vendor/wealth_core/scripts/migrate_v1_db.py \
        --old ~/financial-agent/data/financial_agent.db \
        --new ~/financial-agent/data/wealth_facts.db \
        --dry-run

Review that report, especially any discrepancies it flags, before running it
for real (drop --dry-run) and then pointing this script at the resulting
--new file.

Owner inference: every dotted segment of the key is checked, left to right,
against "shannon" and "partner" literally; the first match found is the
owner (e.g. "income.shannon.paye_salary" -> shannon, and
"legacy.income.shannon.bonusTiming" -> shannon too, even though "shannon" is
the third segment there, not the second). A key with neither segment
anywhere (e.g. "property.main.value") is loaded as "joint" — review the
printed owner assignment before confirming, and re-run with --dry-run if any
look wrong; this script does not guess beyond that one rule.

Exclusion: --exclude-prefix skips any key starting with the given dotted
prefix (repeatable). It defaults to just "legacy." so a Stage 0 run only
loads the curated facts (currently 47) and leaves the uncurated passthrough
behind; pass --exclude-prefix explicitly to change what's excluded (it
replaces the default, it doesn't add to it), or --exclude-prefix "" to
exclude nothing and load everything in the sqlite file.

A successful real run prints one line per fact loaded, ending with
"Loaded N facts for <email>." and exits 0. --dry-run prints the same lines
but writes nothing and ends with "Dry run — nothing written."
"""
import argparse
import os
import sqlite3
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor", "wealth_core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facts_layer import FactStore  # noqa: E402  (sqlite reader for the migrated file)
from app.store import PostgresFactStore  # noqa: E402

DEFAULT_EXCLUDE_PREFIXES = ("legacy.",)


def infer_owner(key: str) -> str:
    for part in key.split("."):
        if part in ("shannon", "partner"):
            return part
    return "joint"


def resolve_exclude_prefixes(raw_prefixes):
    """Turn the raw --exclude-prefix values (None if the flag was never
    passed) into the tuple of prefixes actually used for filtering.

    argparse's `action="append"` appends onto whatever `default` is, so a
    plain `default=DEFAULT_EXCLUDE_PREFIXES` would mean any explicit
    --exclude-prefix ADDS to "legacy." instead of replacing it. We default
    the argument to None instead, and only fall back to
    DEFAULT_EXCLUDE_PREFIXES here, when the flag was never used at all —
    so one explicit --exclude-prefix "" cleanly means "exclude nothing".
    """
    if raw_prefixes is None:
        return DEFAULT_EXCLUDE_PREFIXES
    return tuple(p for p in raw_prefixes if p)


def is_excluded(key: str, exclude_prefixes) -> bool:
    return any(key.startswith(p) for p in exclude_prefixes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, help="Path to wealth_facts.db from migrate_v1_db.py")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--entered-by-email", default=os.environ.get("OWNER_EMAIL"),
                         help="Must already have a users row (sign in once first)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--exclude-prefix", dest="exclude_prefixes", action="append", default=None,
        help=(
            "Dotted key prefix to skip loading (repeatable). Defaults to "
            f"{list(DEFAULT_EXCLUDE_PREFIXES)!r} (Stage 0: curated facts only). "
            "Passing this flag replaces that default rather than adding to "
            "it — pass --exclude-prefix '' to exclude nothing."
        ),
    )
    args = parser.parse_args()
    exclude_prefixes = resolve_exclude_prefixes(args.exclude_prefixes)

    if not args.database_url:
        sys.exit("No --database-url given and DATABASE_URL is not set.")
    if not args.entered_by_email:
        sys.exit("No --entered-by-email given and OWNER_EMAIL is not set.")

    sqlite_conn = sqlite3.connect(args.sqlite)
    sqlite_conn.row_factory = sqlite3.Row
    source_store = FactStore(args.sqlite)
    facts = source_store.current()

    if not facts:
        sys.exit(f"No facts found in {args.sqlite} — nothing to load.")

    pg_conn = psycopg2.connect(args.database_url)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (args.entered_by_email.strip().lower(),))
        row = cur.fetchone()
    if row is None:
        sys.exit(
            f"No user row for {args.entered_by_email}. Sign in to the app once first "
            "so a users row exists, then re-run this script."
        )
    entered_by_user_id = row[0]

    dest_store = PostgresFactStore(pg_conn)

    loaded = 0
    skipped = 0
    for key, fact in sorted(facts.items()):
        if is_excluded(key, exclude_prefixes):
            skipped += 1
            continue
        owner = infer_owner(key)
        print(f"  {key} = {fact.value!r} (as_of={fact.as_of}, owner={owner})")
        if not args.dry_run:
            dest_store.set(fact, owner=owner, entered_by_user_id=entered_by_user_id)
        loaded += 1

    if exclude_prefixes:
        print(f"Excluded {skipped} fact(s) matching prefix(es): {', '.join(exclude_prefixes)}")

    if args.dry_run:
        print("Dry run — nothing written.")
    else:
        print(f"Loaded {loaded} facts for {args.entered_by_email}.")


if __name__ == "__main__":
    main()
