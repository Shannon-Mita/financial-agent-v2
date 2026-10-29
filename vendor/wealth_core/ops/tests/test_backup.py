"""
Tests for ops tooling. The round-trip test is the important one — it proves the
backup can actually be restored and reopened, not merely written.
"""
import os
import tempfile
import pytest

from facts_layer import FactStore, Fact, Unit, Source
from ops import (
    backup_database, verify_backup, restore_database,
    timestamped_backup_name, smoke_test,
)


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _seed_db(path):
    s = FactStore(path)
    s.set(Fact.create("income.shannon.paye_salary", 55000,
                       Unit.GBP_PER_YEAR, Source.USER_STATED, "income"))
    s.set(Fact.create("property.main.mortgage_balance", 375000,
                       Unit.GBP, Source.USER_STATED, "mortgage"))
    s.close()


def test_backup_creates_valid_copy(tmpdir):
    src = os.path.join(tmpdir, "live.db")
    dest = os.path.join(tmpdir, "backup.db")
    _seed_db(src)

    res = backup_database(src, dest)
    assert res.ok is True
    assert res.integrity == "ok"
    assert "facts" in res.tables
    assert res.size_bytes > 0


def test_backup_restore_roundtrip_preserves_data(tmpdir):
    src = os.path.join(tmpdir, "live.db")
    backup = os.path.join(tmpdir, "backup.db")
    restored = os.path.join(tmpdir, "restored.db")
    _seed_db(src)

    backup_database(src, backup)
    res = restore_database(backup, restored)
    assert res.ok is True

    # The restored DB actually contains the data.
    s = FactStore(restored)
    assert s.get("income.shannon.paye_salary").value == 55000
    assert s.get("property.main.mortgage_balance").value == 375000
    s.close()


def test_verify_backup_missing_file(tmpdir):
    res = verify_backup(os.path.join(tmpdir, "nope.db"))
    assert res.ok is False
    assert res.integrity == "missing file"


def test_verify_backup_corrupt_file(tmpdir):
    bad = os.path.join(tmpdir, "corrupt.db")
    with open(bad, "wb") as f:
        f.write(b"this is not a sqlite database")
    res = verify_backup(bad)
    assert res.ok is False


def test_timestamped_name_format():
    from datetime import datetime, timezone
    name = timestamped_backup_name("wealth", now=datetime(2026, 6, 1, 8, 30, 0, tzinfo=timezone.utc))
    assert name == "wealth-backup-20260601T083000Z.db"


def test_smoke_test_passes_on_healthy_system(tmpdir):
    db = os.path.join(tmpdir, "smoke.db")
    res = smoke_test(db)
    assert res.ok is True
    names = {name for name, _, _ in res.checks}
    assert "tax_engine_golden" in names
    assert "facts_store_roundtrip" in names
    assert "unknown_year_rejected" in names


def test_smoke_test_summary_readable(tmpdir):
    db = os.path.join(tmpdir, "smoke.db")
    res = smoke_test(db)
    summary = res.summary()
    assert "PASS" in summary
    assert "tax_engine_golden" in summary
