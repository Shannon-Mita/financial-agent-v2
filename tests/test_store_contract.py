"""
Ports wealth-core's own facts_layer/tests/test_facts.py store scenarios onto
PostgresFactStore, to prove the two stores honour the same contract
(append-only, latest-per-key, history order, as_of reconstruction,
projection). We don't edit or import the original test file — these are the
same scenarios, independently written against the Postgres store.

Requires TEST_DATABASE_URL (a real Postgres) — see tests/conftest.py.
"""
from datetime import date, datetime, timezone

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402


def mk(key, value, unit, category, source=Source.USER_STATED, as_of=None):
    return Fact.create(key, value, unit, source, category, as_of=as_of)


def test_set_and_get_roundtrips_types(pg_conn, owner_user_id):
    s = PostgresFactStore(pg_conn)
    s.set(mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
          owner="shannon", entered_by_user_id=owner_user_id)
    s.set(mk("property.main.has_mortgage", True, Unit.BOOL, "property"),
          owner="joint", entered_by_user_id=owner_user_id)
    s.set(mk("property.main.rate", 4.07, Unit.PERCENT, "property"),
          owner="joint", entered_by_user_id=owner_user_id)
    s.set(mk("people.partner.name", "Alex", Unit.TEXT, "profile"),
          owner="partner", entered_by_user_id=owner_user_id)

    assert s.get("income.shannon.paye_salary").value == 55000
    assert s.get("income.shannon.paye_salary").value.__class__ is int
    assert s.get("property.main.has_mortgage").value is True
    assert s.get("property.main.rate").value == 4.07
    assert s.get("people.partner.name").value == "Alex"


def test_current_returns_latest_per_key(pg_conn, owner_user_id):
    s = PostgresFactStore(pg_conn)
    s.set(mk("property.main.value", 490000, Unit.GBP, "valuation"),
          owner="joint", entered_by_user_id=owner_user_id)
    s.set(mk("property.main.value", 500000, Unit.GBP, "valuation"),
          owner="joint", entered_by_user_id=owner_user_id)
    cur = s.current()
    assert cur["property.main.value"].value == 500000


def test_history_is_append_only_order(pg_conn, owner_user_id):
    s = PostgresFactStore(pg_conn)
    s.set(mk("property.main.mortgage_balance", 387000, Unit.GBP, "mortgage"),
          owner="joint", entered_by_user_id=owner_user_id)
    s.set(mk("property.main.mortgage_balance", 380000, Unit.GBP, "mortgage"),
          owner="joint", entered_by_user_id=owner_user_id)
    s.set(mk("property.main.mortgage_balance", 375000, Unit.GBP, "mortgage"),
          owner="joint", entered_by_user_id=owner_user_id)
    hist = s.history("property.main.mortgage_balance")
    assert [f.value for f in hist] == [387000, 380000, 375000]


def test_get_missing_returns_none(pg_conn, owner_user_id):
    s = PostgresFactStore(pg_conn)
    assert s.get("does.not.exist") is None


def test_as_of_reconstructs_past_state(pg_conn, owner_user_id):
    s = PostgresFactStore(pg_conn)
    early = Fact(
        key="property.main.mortgage_balance", value=387000, unit=Unit.GBP,
        source=Source.USER_STATED, category="mortgage",
        as_of=date(2026, 1, 1),
        entered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    late = Fact(
        key="property.main.mortgage_balance", value=375000, unit=Unit.GBP,
        source=Source.USER_STATED, category="mortgage",
        as_of=date(2026, 7, 1),
        entered_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    s.set(early, owner="joint", entered_by_user_id=owner_user_id)
    s.set(late, owner="joint", entered_by_user_id=owner_user_id)

    march = s.as_of(datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert march["property.main.mortgage_balance"].value == 387000

    august = s.as_of(datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert august["property.main.mortgage_balance"].value == 375000


def test_projection_rebuilds_nested_shape(pg_conn, owner_user_id):
    s = PostgresFactStore(pg_conn)
    s.set(mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
          owner="shannon", entered_by_user_id=owner_user_id)
    s.set(mk("income.partner.paye_salary", 100000, Unit.GBP_PER_YEAR, "income"),
          owner="partner", entered_by_user_id=owner_user_id)
    proj = s.project()
    assert proj["income"]["shannon"]["paye_salary"] == 55000
    assert proj["income"]["partner"]["paye_salary"] == 100000


def test_store_feeds_wealth_core_freshness_gate(pg_conn, owner_user_id):
    """Integration check: PostgresFactStore.current() is drop-in compatible
    with wealth-core's own check_freshness(), unmodified."""
    from datetime import timedelta
    from facts_layer import check_freshness

    s = PostgresFactStore(pg_conn)
    s.set(mk("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income",
             as_of=date.today() - timedelta(days=10)),
          owner="shannon", entered_by_user_id=owner_user_id)
    s.set(mk("cashflow.emergency_savings", 13000, Unit.GBP, "balance",
             as_of=date.today() - timedelta(days=200)),
          owner="joint", entered_by_user_id=owner_user_id)

    res = check_freshness(
        s.current(),
        ["income.shannon.paye_salary", "cashflow.emergency_savings"],
    )
    assert res.ok is False
    stale_keys = {sf.key for sf in res.stale}
    assert stale_keys == {"cashflow.emergency_savings"}


def test_current_with_meta_carries_owner_and_entered_by(pg_conn, owner_user_id, member_user_id):
    s = PostgresFactStore(pg_conn)
    s.set(mk("income.partner.paye_salary", 60000, Unit.GBP_PER_YEAR, "income"),
          owner="partner", entered_by_user_id=member_user_id)
    meta = s.current_with_meta()["income.partner.paye_salary"]
    assert meta.owner == "partner"
    assert meta.entered_by_user_id == member_user_id
    assert meta.fact.value == 60000
