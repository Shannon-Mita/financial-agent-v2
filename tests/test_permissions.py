"""
Pure unit tests for the permission matrix — no Flask, no DB needed. These
are the server-side rules behind the §1 table plus Shannon's amendments.
"""
from app.permissions import can_write_fact, is_protected

PROTECTED_KEYS = ["fire.target_value", "plan.monthly_contribution"]
NON_PROTECTED_KEYS = ["income.partner.paye_salary", "property.main.value"]


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
