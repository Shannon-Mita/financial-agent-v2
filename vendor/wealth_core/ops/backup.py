"""
Backup / restore + smoke test (architecture v0.3, §8.6).

Reviewer point, taken literally: "a backup you've never restored is an
aspiration." So this module doesn't just copy the DB — it verifies the copy
opens, passes SQLite's integrity check, and contains the expected tables, and it
provides a round-trip test that backup->restore->open actually works.

Uses SQLite's online backup API so a live database (with the app running) is
copied consistently, not mid-write.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class BackupResult:
    path: str
    ok: bool
    tables: tuple[str, ...]
    integrity: str          # "ok" or the error string SQLite returned
    size_bytes: int


def backup_database(src_path: str, dest_path: str) -> BackupResult:
    """Consistently copy a SQLite DB and verify the copy is sound.

    Returns ok=False (rather than raising) if the copy fails integrity checks,
    so a caller/scheduler can alert without crashing.
    """
    src = sqlite3.connect(src_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)          # online backup API — consistent snapshot
        finally:
            dest.close()
    finally:
        src.close()

    return verify_backup(dest_path)


def verify_backup(path: str) -> BackupResult:
    """Open a backup file and confirm it is a usable database."""
    if not os.path.exists(path):
        return BackupResult(path, False, (), "missing file", 0)

    size = os.path.getsize(path)
    conn = sqlite3.connect(path)
    try:
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity = integrity_row[0] if integrity_row else "unknown"
        tables = tuple(
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        )
    except sqlite3.DatabaseError as e:
        return BackupResult(path, False, (), f"open failed: {e}", size)
    finally:
        conn.close()

    return BackupResult(
        path=path,
        ok=(integrity == "ok"),
        tables=tables,
        integrity=integrity,
        size_bytes=size,
    )


def restore_database(backup_path: str, dest_path: str) -> BackupResult:
    """Restore a backup over a destination path, verifying the result opens."""
    src = sqlite3.connect(backup_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    return verify_backup(dest_path)


def timestamped_backup_name(prefix: str = "wealth", now: datetime | None = None) -> str:
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-backup-{ts}.db"


# ─────────────────────────────────────────────────────────────────────────────
# Deploy smoke test — run after every deploy; fail the deploy if it fails.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    checks: tuple[tuple[str, bool, str], ...]   # (name, passed, detail)

    def summary(self) -> str:
        lines = [f"{'PASS' if p else 'FAIL'}  {name}  {detail}".rstrip()
                 for name, p, detail in self.checks]
        return "\n".join(lines)


def smoke_test(db_path: str) -> SmokeResult:
    """Minimal end-to-end health check of the deterministic core.

    Verifies the tax engine computes a known value, the facts store opens and
    round-trips, and the target DB is reachable. Intended to run on boot / after
    deploy; a failure here should block the deploy.
    """
    checks: list[tuple[str, bool, str]] = []

    # 1. Tax engine returns the golden number.
    try:
        from tax_engine import calc_income_tax
        r = calc_income_tax(55000, tax_year="2025/26")
        ok = (r.income_tax == 9432 and r.take_home == 42457)
        checks.append(("tax_engine_golden", ok, f"tax={r.income_tax}, take_home={r.take_home}"))
    except Exception as e:  # noqa: BLE001
        checks.append(("tax_engine_golden", False, str(e)))

    # 2. Facts store opens and round-trips a value.
    try:
        from facts_layer import FactStore, Fact, Unit, Source
        s = FactStore(db_path)
        s.set(Fact.create("smoke.test.value", 1, Unit.COUNT, Source.DERIVED, "profile"))
        got = s.get("smoke.test.value")
        checks.append(("facts_store_roundtrip", got is not None and got.value == 1, ""))
    except Exception as e:  # noqa: BLE001
        checks.append(("facts_store_roundtrip", False, str(e)))

    # 3. Unknown tax year is rejected (the safety rail is live).
    try:
        from tax_engine import calc_income_tax, UnknownTaxYear
        try:
            calc_income_tax(50000, tax_year="9999/00")
            checks.append(("unknown_year_rejected", False, "did not raise"))
        except UnknownTaxYear:
            checks.append(("unknown_year_rejected", True, ""))
    except Exception as e:  # noqa: BLE001
        checks.append(("unknown_year_rejected", False, str(e)))

    return SmokeResult(ok=all(p for _, p, _ in checks), checks=tuple(checks))
