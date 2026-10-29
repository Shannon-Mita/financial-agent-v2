"""
Postgres-backed fact store implementing the same contract as wealth-core's
own FactStore (set/get/current/history/as_of/project), plus the `owner` and
`entered_by_user_id` metadata the permission rules need. wealth-core's sqlite
FactStore is untouched — this is a parallel implementation for the hosted app,
not a modification of vendor/wealth_core/facts_layer/store.py.

Value (en/de)coding is imported from wealth-core's own store module rather
than reimplemented, so the two stores stay byte-for-byte consistent in how
they round-trip bool/int/float/text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from . import vendor_path  # noqa: F401  (adds vendor/wealth_core to sys.path)
from facts_layer import Fact, Source, Unit
from facts_layer.store import _adapt_value, _restore_value


@dataclass(frozen=True)
class FactMeta:
    """Owner/audit metadata alongside a Fact, for permission checks."""
    id: int
    key: str
    owner: str
    entered_by_user_id: int
    fact: Fact


class PostgresFactStore:
    def __init__(self, conn):
        self.conn = conn

    # ── Writes (append-only — DB trigger also enforces this) ───────────────

    def set(self, fact: Fact, owner: str, entered_by_user_id: int) -> None:
        text, tag = _adapt_value(fact.value)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO facts
                  (key, value_text, value_type, unit, source, category,
                   owner, as_of, entered_at, note, entered_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fact.key, text, tag, fact.unit.value, fact.source.value,
                    fact.category, owner, fact.as_of, fact.entered_at,
                    fact.note, entered_by_user_id,
                ),
            )
        self.conn.commit()

    # ── Reads ────────────────────────────────────────────────────────────

    def _row_to_fact(self, row) -> Fact:
        (key, value_text, value_type, unit, source, category,
         as_of, entered_at, note) = row
        return Fact(
            key=key,
            value=_restore_value(value_text, value_type),
            unit=Unit(unit),
            source=Source(source),
            category=category,
            as_of=as_of,
            entered_at=entered_at,
            note=note,
        )

    def current(self) -> dict[str, Fact]:
        """Latest fact per key — matches wealth-core's FactStore.current()."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.key, f.value_text, f.value_type, f.unit, f.source,
                       f.category, f.as_of, f.entered_at, f.note
                FROM facts f
                JOIN (
                    SELECT key, MAX(entered_at) AS max_entered
                    FROM facts GROUP BY key
                ) latest
                ON f.key = latest.key AND f.entered_at = latest.max_entered
                """
            )
            rows = cur.fetchall()
        return {r[0]: self._row_to_fact(r) for r in rows}

    def current_with_meta(self) -> dict[str, FactMeta]:
        """Like current(), but including owner + who entered it — what the
        permission layer and dashboard template need that the plain
        wealth-core contract has no reason to carry."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.id, f.key, f.value_text, f.value_type, f.unit,
                       f.source, f.category, f.owner, f.as_of, f.entered_at,
                       f.note, f.entered_by_user_id
                FROM facts f
                JOIN (
                    SELECT key, MAX(entered_at) AS max_entered
                    FROM facts GROUP BY key
                ) latest
                ON f.key = latest.key AND f.entered_at = latest.max_entered
                """
            )
            rows = cur.fetchall()
        out = {}
        for (fid, key, value_text, value_type, unit, source, category,
             owner, as_of, entered_at, note, entered_by) in rows:
            fact = self._row_to_fact(
                (key, value_text, value_type, unit, source, category,
                 as_of, entered_at, note)
            )
            out[key] = FactMeta(
                id=fid, key=key, owner=owner,
                entered_by_user_id=entered_by, fact=fact,
            )
        return out

    def get(self, key: str) -> Fact | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT key, value_text, value_type, unit, source, category,
                       as_of, entered_at, note
                FROM facts WHERE key = %s ORDER BY entered_at DESC LIMIT 1
                """,
                (key,),
            )
            row = cur.fetchone()
        return self._row_to_fact(row) if row else None

    def get_meta(self, key: str) -> FactMeta | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, owner, entered_by_user_id
                FROM facts WHERE key = %s ORDER BY entered_at DESC LIMIT 1
                """,
                (key,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        fact = self.get(key)
        return FactMeta(id=row[0], key=key, owner=row[1], entered_by_user_id=row[2], fact=fact)

    def history(self, key: str) -> list[Fact]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT key, value_text, value_type, unit, source, category,
                       as_of, entered_at, note
                FROM facts WHERE key = %s ORDER BY entered_at ASC
                """,
                (key,),
            )
            rows = cur.fetchall()
        return [self._row_to_fact(r) for r in rows]

    def as_of(self, when: datetime) -> dict[str, Fact]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.key, f.value_text, f.value_type, f.unit, f.source,
                       f.category, f.as_of, f.entered_at, f.note
                FROM facts f
                JOIN (
                    SELECT key, MAX(entered_at) AS max_entered
                    FROM facts WHERE entered_at <= %s GROUP BY key
                ) latest
                ON f.key = latest.key AND f.entered_at = latest.max_entered
                """,
                (when,),
            )
            rows = cur.fetchall()
        return {r[0]: self._row_to_fact(r) for r in rows}

    def project(self) -> dict:
        """Same nested-dict projection as wealth-core's FactStore.project()."""
        out: dict = {}
        for key, fact in self.current().items():
            parts = key.split(".")
            node = out
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = fact.value
        return out
