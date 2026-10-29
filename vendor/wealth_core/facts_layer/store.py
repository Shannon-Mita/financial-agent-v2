"""
Append-only SQLite fact store (architecture v0.3, Layer 1).

Design choices:
  - APPEND-ONLY. Every set() inserts a new row. We never UPDATE or DELETE a
    fact's value. "Current" = the latest row per key. This is what gives us
    history and the ability to reconstruct past beliefs (audit trail).
  - No ORM. Plain sqlite3 with parameterised queries. WAL mode for concurrent
    read while a scheduled job writes.
  - Values are stored as text with a type tag and coerced back on read, so we
    never reintroduce the string/number bug — reads return correctly typed
    Python values.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

from .models import Fact, Source, Unit


def _adapt_value(value: object) -> tuple[str, str]:
    """(stored_text, type_tag) so we can round-trip the Python type exactly."""
    if isinstance(value, bool):
        return ("1" if value else "0", "bool")
    if isinstance(value, int):
        return (str(value), "int")
    if isinstance(value, float):
        return (repr(value), "float")
    return (str(value), "text")


def _restore_value(text: str, tag: str) -> object:
    if tag == "bool":
        return text == "1"
    if tag == "int":
        return int(text)
    if tag == "float":
        return float(text)
    return text


class FactStore:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT NOT NULL,
                value_text  TEXT NOT NULL,
                value_type  TEXT NOT NULL,
                unit        TEXT NOT NULL,
                source      TEXT NOT NULL,
                category    TEXT NOT NULL,
                as_of       TEXT NOT NULL,      -- ISO date
                entered_at  TEXT NOT NULL,      -- ISO datetime (UTC)
                note        TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Index for "latest per key" lookups.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_facts_key_entered "
            "ON facts(key, entered_at)"
        )
        self.conn.commit()

    # ── Writes (append-only) ─────────────────────────────────────────────────

    def set(self, fact: Fact) -> None:
        text, tag = _adapt_value(fact.value)
        self.conn.execute(
            """
            INSERT INTO facts
              (key, value_text, value_type, unit, source, category, as_of, entered_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact.key, text, tag, fact.unit.value, fact.source.value,
                fact.category, fact.as_of.isoformat(),
                fact.entered_at.isoformat(), fact.note,
            ),
        )
        self.conn.commit()

    def set_many(self, facts: list[Fact]) -> None:
        for f in facts:
            self.set(f)

    # ── Reads ────────────────────────────────────────────────────────────────

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        return Fact(
            key=row["key"],
            value=_restore_value(row["value_text"], row["value_type"]),
            unit=Unit(row["unit"]),
            source=Source(row["source"]),
            category=row["category"],
            as_of=date.fromisoformat(row["as_of"]),
            entered_at=datetime.fromisoformat(row["entered_at"]),
            note=row["note"],
        )

    def current(self) -> dict[str, Fact]:
        """Latest fact per key — the household's current believed state."""
        rows = self.conn.execute(
            """
            SELECT f.* FROM facts f
            JOIN (
                SELECT key, MAX(entered_at) AS max_entered
                FROM facts GROUP BY key
            ) latest
            ON f.key = latest.key AND f.entered_at = latest.max_entered
            """
        ).fetchall()
        return {r["key"]: self._row_to_fact(r) for r in rows}

    def get(self, key: str) -> Fact | None:
        row = self.conn.execute(
            "SELECT * FROM facts WHERE key = ? ORDER BY entered_at DESC LIMIT 1",
            (key,),
        ).fetchone()
        return self._row_to_fact(row) if row else None

    def history(self, key: str) -> list[Fact]:
        """Every recorded value for a key, oldest first — the audit trail."""
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE key = ? ORDER BY entered_at ASC", (key,)
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def as_of(self, when: datetime) -> dict[str, Fact]:
        """What we believed at a past moment — reconstructs historical state.

        Returns the latest fact per key whose entered_at <= `when`. This is how a
        past recommendation is reproduced: feed the calculator the facts as they
        stood when the recommendation was made.
        """
        rows = self.conn.execute(
            """
            SELECT f.* FROM facts f
            JOIN (
                SELECT key, MAX(entered_at) AS max_entered
                FROM facts WHERE entered_at <= ? GROUP BY key
            ) latest
            ON f.key = latest.key AND f.entered_at = latest.max_entered
            """,
            (when.isoformat(),),
        ).fetchall()
        return {r["key"]: self._row_to_fact(r) for r in rows}

    # ── UI projection ────────────────────────────────────────────────────────

    def project(self) -> dict:
        """Nested dict projection of current facts, for the UI / templates.

        Convenience only — the facts remain the source of truth. Rebuilds the
        familiar profile shape from dotted keys, e.g.
        "income.shannon.paye_salary" -> {"income": {"shannon": {"paye_salary": ...}}}
        """
        out: dict = {}
        for key, fact in self.current().items():
            parts = key.split(".")
            node = out
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = fact.value
        return out

    def close(self):
        self.conn.close()
