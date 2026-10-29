"""
Pure unit tests for the permission matrix — no Flask, no DB needed. These
are the server-side rules behind the §1 table plus Shannon's amendments.
"""
import pytest

from app.permissions import (
    CREATABLE_FACT_KEYS,
    PROTECTED_KEY_PREFIXES,
    can_create_fact,
    can_create_task,
    can_edit_or_delete_task,
    can_toggle_goal_status,
    can_toggle_task,
    can_write_fact,
    is_protected,
)

PROTECTED_KEYS = ["fire.target_value", "plan.monthly_contribution"]
NON_PROTECTED_KEYS = ["income.partner.paye_salary", "property.main.value"]

# The six goals.* keys the v1 migration (vendor/wealth_core/migrate/from_v1.py)
# actually produces — these load as owner=joint in Stage 0, but must stay
# owner-only to write regardless, same as fire.target/plan. above.
GOALS_KEYS = [
    "goals.fire.target_monthly_income",
    "goals.fire.target_age",
    "goals.fire.swr",
    "goals.fire.target_years",
    "goals.fire.target_number",
    "goals.net_worth.target_amount",
]

# Same six keys, with placeholder (not real) values + units matching
# from_v1.py's curated mapping, for the HTTP-level round-trip tests below.
# (key, Unit member name, initial value, raw posted value, expected new value)
GOALS_KEY_SPECS = [
    ("goals.fire.target_monthly_income", "GBP_PER_MONTH", 8000.0, "9000", 9000.0),
    ("goals.fire.target_age", "COUNT", 45, "46", 46),
    ("goals.fire.swr", "PERCENT", 4.0, "3.5", 3.5),
    ("goals.fire.target_years", "COUNT", 9, "10", 10),
    ("goals.fire.target_number", "GBP", 2_400_000, "2500000", 2500000),
    ("goals.net_worth.target_amount", "GBP", 2_400_000, "2500000", 2500000),
]


def test_protected_keys_detected():
    for key in PROTECTED_KEYS:
        assert is_protected(key)


def test_non_protected_keys_not_flagged():
    for key in NON_PROTECTED_KEYS:
        assert not is_protected(key)


def test_owner_can_write_anything():
    assert can_write_fact("owner", "shannon", "income.shannon.paye_salary")
    assert can_write_fact("owner", "partner", "income.partner.paye_salary")
    assert can_write_fact("owner", "joint", "property.main.value")
    for key in PROTECTED_KEYS:
        assert can_write_fact("owner", "joint", key)


def test_member_can_write_own_facts():
    assert can_write_fact("member", "partner", "income.partner.paye_salary")


def test_member_can_write_joint_facts():
    assert can_write_fact("member", "joint", "property.main.value")


def test_member_cannot_write_shannon_owned_facts():
    assert not can_write_fact("member", "shannon", "income.shannon.paye_salary")


def test_member_cannot_write_protected_keys_even_if_owner_is_joint():
    for key in PROTECTED_KEYS:
        assert not can_write_fact("member", "joint", key)


def test_member_cannot_write_protected_keys_even_if_owner_is_partner():
    assert not can_write_fact("member", "partner", "fire.target_value")


def test_unknown_role_denied():
    assert not can_write_fact("someone-else", "joint", "property.main.value")


# ── goals.* coverage — these migrate in as owner=joint but must never be ──
# ── writable by the partner (Shannon's amendment, same rationale as the ──
# ── FIRE target and plan settings above). ──────────────────────────────

def test_goals_prefix_is_in_protected_list():
    assert "goals." in PROTECTED_KEY_PREFIXES


@pytest.mark.parametrize("key", GOALS_KEYS)
def test_every_real_goals_key_is_protected(key):
    assert is_protected(key)


@pytest.mark.parametrize("key", GOALS_KEYS)
def test_member_cannot_write_any_goals_key_even_when_owner_is_joint(key):
    assert not can_write_fact("member", "joint", key)


@pytest.mark.parametrize("key", GOALS_KEYS)
def test_owner_can_write_every_goals_key(key):
    assert can_write_fact("owner", "joint", key)


def test_goals_regression_against_real_curated_migration():
    """Ties the protected list to the actual migration output, not just a
    hand-maintained key list — if from_v1.py's curated mapping ever changes
    the set of goals.* keys it produces, this fails until the protected list
    is updated to match, instead of silently drifting out of sync."""
    from app.vendor_path import ensure_on_path

    ensure_on_path()
    from migrate import migrate_v1_profile
    from migrate.tests.test_from_v1 import AS_OF, synthetic_blob

    facts, _report = migrate_v1_profile(synthetic_blob(), AS_OF)
    curated_keys = [f.key for f in facts if not f.key.startswith("legacy.")]

    assert len(curated_keys) == 47  # Stage 0's curated fact count

    goals_keys_from_migration = sorted(k for k in curated_keys if k.startswith("goals."))
    assert goals_keys_from_migration == sorted(GOALS_KEYS)  # keep both lists in sync

    for key in goals_keys_from_migration:
        assert is_protected(key), f"{key} is produced by the migration but not protected"


# ── End-to-end over HTTP: proves the 403 is enforced server-side on the ────
# ── real route, not just in the permission function in isolation. ─────────

def test_partner_gets_403_on_protected_key_even_when_owner_is_joint(client, pg_conn, member_user_id):
    from app.store import PostgresFactStore
    from app.vendor_path import ensure_on_path

    ensure_on_path()
    from facts_layer import Fact, Source, Unit

    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("fire.target_value", 1_000_000, Unit.GBP, Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=member_user_id,
    )

    with client.session_transaction() as sess:
        sess["_user_id"] = str(member_user_id)

    page = client.get("/")
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)

    resp = client.post(
        "/facts/fire.target_value/update",
        data={"value": "2000000", "csrf_token": token},
    )
    assert resp.status_code == 403
    assert store.get("fire.target_value").value == 1_000_000  # unchanged


@pytest.mark.parametrize("key,unit_name,initial_value,new_raw,new_expected", GOALS_KEY_SPECS)
def test_partner_gets_403_on_every_goals_key_even_when_owner_is_joint(
    client, pg_conn, member_user_id, key, unit_name, initial_value, new_raw, new_expected
):
    import re

    from app.store import PostgresFactStore
    from app.vendor_path import ensure_on_path

    ensure_on_path()
    from facts_layer import Fact, Source, Unit

    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create(key, initial_value, getattr(Unit, unit_name), Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=member_user_id,
    )

    with client.session_transaction() as sess:
        sess["_user_id"] = str(member_user_id)

    page = client.get("/")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)

    resp = client.post(
        f"/facts/{key}/update",
        data={"value": new_raw, "csrf_token": token},
    )
    assert resp.status_code == 403
    assert store.get(key).value == initial_value  # unchanged


@pytest.mark.parametrize("key,unit_name,initial_value,new_raw,new_expected", GOALS_KEY_SPECS)
def test_owner_can_write_every_goals_key_over_http_even_when_owner_is_joint(
    client, pg_conn, owner_user_id, key, unit_name, initial_value, new_raw, new_expected
):
    import re

    from app.store import PostgresFactStore
    from app.vendor_path import ensure_on_path

    ensure_on_path()
    from facts_layer import Fact, Source, Unit

    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create(key, initial_value, getattr(Unit, unit_name), Source.USER_STATED, "goal"),
        owner="joint", entered_by_user_id=owner_user_id,
    )

    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner_user_id)

    page = client.get("/")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)

    resp = client.post(
        f"/facts/{key}/update",
        data={"value": new_raw, "csrf_token": token},
    )
    assert resp.status_code == 204
    assert store.get(key).value == new_expected


# ── Stage 1: create-if-missing fact registry ───────────────────────────────

def test_creatable_fact_keys_is_exactly_the_approved_registry():
    """Pins the registry to the two keys Shannon approved — fails loudly if
    a key is added or removed without an explicit decision."""
    assert CREATABLE_FACT_KEYS == frozenset({
        "goals.fire.target_date",
        "savings.house_deposit.balance",
    })


@pytest.mark.parametrize("key", list(CREATABLE_FACT_KEYS))
def test_owner_can_create_every_registered_key(key):
    assert can_create_fact("owner", key)


@pytest.mark.parametrize("key", list(CREATABLE_FACT_KEYS))
def test_member_cannot_create_any_registered_key(key):
    assert not can_create_fact("member", key)


def test_unknown_key_is_rejected_even_for_owner():
    """The registry is a strict allowlist — an owner cannot create an
    arbitrary key just by posting to it, only the curated ones above."""
    assert not can_create_fact("owner", "income.shannon.paye_salary")
    assert not can_create_fact("owner", "some.made.up.key")


def test_unknown_role_cannot_create():
    assert not can_create_fact("someone-else", "goals.fire.target_date")


# ── Stage 1: create-if-missing wired to the real /facts/<key>/update route ─

def test_http_owner_can_create_a_registered_missing_key(client, pg_conn, owner_user_id):
    import re

    from app.store import PostgresFactStore

    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner_user_id)
    page = client.get("/")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)

    resp = client.post(
        "/facts/goals.fire.target_date/update",
        data={"value": "2030-10-05", "csrf_token": token},
    )
    assert resp.status_code == 204
    store = PostgresFactStore(pg_conn)
    assert store.get("goals.fire.target_date").value == "2030-10-05"


def test_http_member_gets_403_creating_a_registered_missing_key(client, pg_conn, member_user_id):
    import re

    from app.store import PostgresFactStore

    with client.session_transaction() as sess:
        sess["_user_id"] = str(member_user_id)
    page = client.get("/")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)

    resp = client.post(
        "/facts/savings.house_deposit.balance/update",
        data={"value": "5000", "csrf_token": token},
    )
    assert resp.status_code == 403
    store = PostgresFactStore(pg_conn)
    assert store.get("savings.house_deposit.balance") is None


def test_http_unknown_key_rejected_even_for_owner(client, pg_conn, owner_user_id):
    """An unregistered key is 404, not 403 — it isn't a thing that can be
    brought into existence via this endpoint, regardless of role."""
    import re

    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner_user_id)
    page = client.get("/")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.data.decode()).group(1)

    resp = client.post(
        "/facts/some.made.up.key/update",
        data={"value": "1", "csrf_token": token},
    )
    assert resp.status_code == 404


# ── Stage 1: tasks ───────────────────────────────────────────────────────

def test_owner_can_create_any_task():
    assert can_create_task("owner", 1, assignee_user_id=2)
    assert can_create_task("owner", 1, assignee_user_id=None)


def test_member_can_only_create_a_task_assigned_to_herself():
    assert can_create_task("member", 2, assignee_user_id=2)
    assert not can_create_task("member", 2, assignee_user_id=1)  # assigned to Shannon
    assert not can_create_task("member", 2, assignee_user_id=None)  # unassigned


def test_owner_can_edit_or_delete_any_task():
    assert can_edit_or_delete_task("owner", 1, creator_user_id=2, assignee_user_id=2)


def test_member_can_edit_or_delete_only_her_own_task():
    # Created by her, still assigned to her — "her own".
    assert can_edit_or_delete_task("member", 2, creator_user_id=2, assignee_user_id=2)


def test_member_cannot_edit_or_delete_a_task_created_by_shannon():
    assert not can_edit_or_delete_task("member", 2, creator_user_id=1, assignee_user_id=2)


def test_member_cannot_edit_or_delete_a_task_assigned_to_shannon():
    assert not can_edit_or_delete_task("member", 2, creator_user_id=2, assignee_user_id=1)


def test_owner_can_toggle_any_task():
    assert can_toggle_task("owner", 1, assignee_user_id=2)


def test_member_can_toggle_only_her_own_assigned_task():
    assert can_toggle_task("member", 2, assignee_user_id=2)
    assert not can_toggle_task("member", 2, assignee_user_id=1)   # his task
    assert not can_toggle_task("member", 2, assignee_user_id=None)  # unassigned


# ── Stage 1: goal status toggling (binary/habit only, member-assigned) ────

def test_owner_can_toggle_any_goal_status():
    assert can_toggle_goal_status("owner", 1, "target", assignee_user_ids=[2])


def test_member_can_toggle_binary_or_habit_goal_assigned_to_her():
    assert can_toggle_goal_status("member", 2, "binary", assignee_user_ids=[2])
    assert can_toggle_goal_status("member", 2, "habit", assignee_user_ids=[2])


def test_member_cannot_toggle_a_target_goal_even_if_assigned():
    assert not can_toggle_goal_status("member", 2, "target", assignee_user_ids=[2])


def test_member_cannot_toggle_a_goal_she_is_not_assigned_to():
    assert not can_toggle_goal_status("member", 2, "binary", assignee_user_ids=[1])


# ── Stage 1: @owner_required decorator, over HTTP ──────────────────────────
# No goals/tasks routes exist yet (that's step iii) — this exercises the
# decorator itself against an ad-hoc view, registered before the first
# request so Flask accepts the extra rule.

def test_owner_required_lets_owner_through(app, pg_conn, owner_user_id):
    from app.permissions import owner_required

    @app.route("/_test/owner-only")
    @owner_required
    def _owner_only():
        return "ok", 200

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner_user_id)
    resp = client.get("/_test/owner-only")
    assert resp.status_code == 200


def test_owner_required_blocks_member(app, pg_conn, member_user_id):
    from app.permissions import owner_required

    @app.route("/_test/owner-only-2")
    @owner_required
    def _owner_only_2():
        return "ok", 200

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(member_user_id)
    resp = client.get("/_test/owner-only-2")
    assert resp.status_code == 403


def test_owner_required_redirects_unauthenticated(app, pg_conn):
    from app.permissions import owner_required

    @app.route("/_test/owner-only-3")
    @owner_required
    def _owner_only_3():
        return "ok", 200

    client = app.test_client()
    resp = client.get("/_test/owner-only-3")
    assert resp.status_code in (302, 401)
