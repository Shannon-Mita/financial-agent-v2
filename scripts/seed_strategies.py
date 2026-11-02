#!/usr/bin/env python3
"""
One-off seed: loads docs/STRATEGY_WORKSHEET.md's 15 strategies into the
strategies table. Refuses outright if the strategies table already has a
single row — this is a from-empty seed only, not a merge (same guard
pattern as scripts/restore_data.py's refuse_unless_empty).

Every worksheet "?" stays unknown: NULL for detail/status/the two numeric
effect fields, "unknown" for risks_childcare_eligibility (its own enum
value, not NULL). A genuine, known zero effect (strategy 8) is stored as
the number 0, not NULL — the two are never confused. "n/a" (a real,
non-numeric answer, distinct from "unknown") is kept as literal text.

Reads DATABASE_URL from the environment — never prints it. The whole seed
is one transaction: any error rolls back everything, never leaving a
half-seeded table.

A successful run prints:
    Seeded 15 strategies from docs/STRATEGY_WORKSHEET.md
"""
import os
import re
import sys

import psycopg2

WORKSHEET_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "STRATEGY_WORKSHEET.md")

# The worksheet's own section headings double as the `area` column's
# values verbatim (Shannon, 1 Nov 2026) — no translation layer needed.
AREA_HEADINGS = frozenset({
    "Work and income", "Relocation", "Business", "Investing", "Property", "Spending",
})

_HEADING_RE = re.compile(r"^## (.+)$")
_TITLE_RE = re.compile(r"^### \d+\.\s*(.+)$")
_FIELD_RE = re.compile(r"^- ([^:]+):\s*(.*)$")


class NotEmptyError(RuntimeError):
    pass


def refuse_unless_empty(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM strategies")
        if cur.fetchone()[0] > 0:
            raise NotEmptyError("Refusing to seed: strategies already has rows.")


def parse_worksheet(text: str) -> list[dict]:
    """Returns a list of {"area": str, "title": str, "fields": dict} —
    `fields` keyed by the worksheet's own field labels exactly ("Effect on
    net worth", "Status", "Detail", etc.), values as raw strings
    (including the literal "?" for unknown) for the caller to interpret."""
    entries: list[dict] = []
    area = None
    last_field_key = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if line.strip() == "---":
            last_field_key = None
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            if heading_match.group(1) in AREA_HEADINGS:
                area = heading_match.group(1)
            last_field_key = None
            continue

        title_match = _TITLE_RE.match(line)
        if title_match:
            entries.append({"area": area, "title": title_match.group(1).strip(), "fields": {}})
            last_field_key = None
            continue

        field_match = _FIELD_RE.match(line)
        if field_match and entries:
            key = field_match.group(1).strip()
            value = field_match.group(2).strip()
            entries[-1]["fields"][key] = value
            last_field_key = key
            continue

        # A continuation line (e.g. a Detail that wraps) — glue it onto
        # the previous field's value rather than dropping it.
        stripped = line.strip()
        if stripped and entries and last_field_key:
            entries[-1]["fields"][last_field_key] += " " + stripped

    return entries


def _unknown_or(value: str | None) -> str | None:
    """"?" -> None (unknown). Anything else, including "n/a" (a real,
    non-numeric answer), passes through unchanged."""
    if value is None or value == "?":
        return None
    return value


def _unknown_or_numeric(value: str | None) -> float | None:
    if value is None or value == "?":
        return None
    return float(value)


def _risks_value(value: str | None) -> str:
    if value is None or value == "?":
        return "unknown"
    return value


def seed_all(conn, entries: list[dict], *, owner_id: int) -> int:
    refuse_unless_empty(conn)
    with conn.cursor() as cur:
        for entry in entries:
            fields = entry["fields"]
            cur.execute(
                """
                INSERT INTO strategies
                  (title, detail, area, status, work_lives_in,
                   effect_on_net_worth, effect_on_passive_income,
                   risks_childcare_eligibility, from_when, source,
                   created_by_user_id, updated_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry["title"],
                    _unknown_or(fields.get("Detail")),
                    entry["area"],
                    _unknown_or(fields.get("Status")),
                    fields.get("Work lives in", ""),
                    _unknown_or_numeric(fields.get("Effect on net worth")),
                    _unknown_or_numeric(fields.get("Effect on passive income")),
                    _risks_value(fields.get("Risks childcare eligibility")),
                    _unknown_or(fields.get("From when")),
                    "shannon",
                    owner_id,
                    owner_id,
                ),
            )
    conn.commit()
    return len(entries)


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    with open(WORKSHEET_PATH) as f:
        entries = parse_worksheet(f.read())
    if len(entries) != 15:
        sys.exit(f"Expected exactly 15 strategies in the worksheet, found {len(entries)}.")

    conn = psycopg2.connect(database_url)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE role = 'owner' LIMIT 1")
        row = cur.fetchone()
    if row is None:
        sys.exit("No owner user found — create the owner account before seeding.")
    owner_id = row[0]

    try:
        count = seed_all(conn, entries, owner_id=owner_id)
    except Exception as exc:
        conn.rollback()
        sys.exit(str(exc))

    print(f"Seeded {count} strategies from {WORKSHEET_PATH}")


if __name__ == "__main__":
    main()
