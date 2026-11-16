"""
HTTP-level tests for strategy notes (notes & context feature) — both
Shannon and Asha can add a note to any strategy or any step (not gated by
ownership/assignment, same unconditional rule as can_edit_strategy), there
is no edit or delete route at all (append-only, nothing to call), links
must be well-formed https:// URLs with a real host, and body/link have
clear-error length caps. Needs a real Postgres (skips without
TEST_DATABASE_URL).
"""
import re

import app.strategies_store as strategies_store
import app.strategy_notes_store as strategy_notes_store

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m, "expected a csrf_token hidden input on the page"
    return m.group(1)


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def _make_strategy(pg_conn, owner_user_id, **overrides):
    fields = dict(
        title="Strategy", detail="", area="Business", status="idea",
        work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )
    fields.update(overrides)
    return strategies_store.create_strategy(pg_conn, **fields)


# ── Both can add, to any strategy/step — permission tests for Asha ──────

def test_owner_can_add_a_note_to_a_strategy(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "Looked into this.", "csrf_token": token(page),
    })
    assert resp.status_code == 302
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    assert len(notes) == 1
    assert notes[0]["created_by_user_id"] == owner_user_id


def test_member_can_add_a_note_to_any_strategy_not_just_her_own(client, pg_conn, owner_user_id, member_user_id):
    # Strategy created by Shannon — Asha still gets to add a note to it,
    # same unconditional rule as can_edit_strategy, not gated by who made it.
    strategy_id = _make_strategy(pg_conn, owner_user_id, source="shannon")
    login(client, member_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "Asha's research.", "csrf_token": token(page),
    })
    assert resp.status_code == 302
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    assert len(notes) == 1
    assert notes[0]["created_by_user_id"] == member_user_id


def test_member_can_add_a_note_to_a_step_she_is_not_the_assignee_of(client, pg_conn, owner_user_id, member_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Owner's step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "A thought on this step.", "step_id": str(step_id), "csrf_token": token(page),
    })
    assert resp.status_code == 302
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    assert notes[0]["step_id"] == step_id


def test_notes_allowed_on_an_archived_strategy(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    strategies_store.archive_strategy(
        pg_conn, strategy_id, reason="No longer relevant", archived_date="2026-11-10", user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "Still worth recording why.", "csrf_token": token(page),
    })
    assert resp.status_code == 302
    assert len(strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)) == 1


def test_notes_allowed_on_a_done_step(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Step", assignee_user_id=owner_user_id, user_id=owner_user_id,
    )
    strategies_store.toggle_strategy_step(pg_conn, step_id, True, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "Note on a completed step.", "step_id": str(step_id), "csrf_token": token(page),
    })
    assert resp.status_code == 302
    assert len(strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)) == 1


# ── Validation ────────────────────────────────────────────────────────────

def test_missing_body_is_rejected(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={"csrf_token": token(page)})
    assert resp.status_code == 400
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_body_over_10000_characters_is_rejected_with_a_clear_message(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "x" * 10001, "csrf_token": token(page),
    })
    assert resp.status_code == 400
    assert b"10,000" in resp.data or b"10000" in resp.data
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_body_at_exactly_10000_characters_is_allowed(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "x" * 10000, "csrf_token": token(page),
    })
    assert resp.status_code == 302


def test_a_well_formed_https_link_is_accepted(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "See this.", "link": "https://example.com/research", "csrf_token": token(page),
    })
    assert resp.status_code == 302
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)[0]["link"] == "https://example.com/research"


def test_a_plain_http_link_is_rejected(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "See this.", "link": "http://example.com", "csrf_token": token(page),
    })
    assert resp.status_code == 400
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_a_hostless_https_link_is_rejected(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "See this.", "link": "https:///no-host", "csrf_token": token(page),
    })
    assert resp.status_code == 400
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_a_malformed_link_is_rejected(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "See this.", "link": "not a url at all", "csrf_token": token(page),
    })
    assert resp.status_code == 400
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_a_link_over_2048_characters_is_rejected_with_a_clear_message(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    too_long = "https://example.com/" + ("a" * 2048)
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "See this.", "link": too_long, "csrf_token": token(page),
    })
    assert resp.status_code == 400
    assert b"2,048" in resp.data or b"2048" in resp.data
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_blank_link_is_treated_as_no_link(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "No link here.", "link": "", "csrf_token": token(page),
    })
    assert resp.status_code == 302
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)[0]["link"] is None


def test_a_step_id_from_a_different_strategy_is_rejected(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id, title="A")
    other_strategy_id = _make_strategy(pg_conn, owner_user_id, title="B")
    other_step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=other_strategy_id, title="Step on B", assignee_user_id=None, user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    resp = client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "Wrong strategy for this step.", "step_id": str(other_step_id), "csrf_token": token(page),
    })
    assert resp.status_code == 400
    assert strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id) == []


def test_notes_on_a_nonexistent_strategy_404s(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/goals")
    resp = client.post("/strategies/999999/notes", data={"body": "Hi", "csrf_token": token(page)})
    assert resp.status_code == 404


# ── Append-only: no edit or delete route exists at all ───────────────────

def test_no_edit_or_delete_route_exists_for_notes(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    client.post(f"/strategies/{strategy_id}/notes", data={"body": "Note", "csrf_token": token(page)})
    note_id = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)[0]["id"]

    assert client.get(f"/strategy-notes/{note_id}/edit").status_code == 404
    assert client.post(f"/strategy-notes/{note_id}/edit", data={"csrf_token": token(page)}).status_code == 404
    assert client.post(f"/strategy-notes/{note_id}/delete", data={"csrf_token": token(page)}).status_code == 404


# ── Displayed on the strategy page, newest first ─────────────────────────

def test_notes_shown_on_the_strategy_page_newest_first(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    client.post(f"/strategies/{strategy_id}/notes", data={"body": "Older note", "csrf_token": token(page)})
    page = client.get(f"/strategies/{strategy_id}")
    client.post(f"/strategies/{strategy_id}/notes", data={"body": "Newer note", "csrf_token": token(page)})

    body = client.get(f"/strategies/{strategy_id}").data.decode()
    assert body.find("Newer note") < body.find("Older note")


def test_step_scoped_note_shown_under_its_step(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Specific step", assignee_user_id=None, user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get(f"/strategies/{strategy_id}")
    client.post(f"/strategies/{strategy_id}/notes", data={
        "body": "A note pinned to the step.", "step_id": str(step_id), "csrf_token": token(page),
    })
    body = client.get(f"/strategies/{strategy_id}").data.decode()
    assert "A note pinned to the step." in body
    assert body.find("Specific step") < body.find("A note pinned to the step.")


def test_login_required(client, pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    resp = client.post(f"/strategies/{strategy_id}/notes", data={"body": "Note"})
    assert resp.status_code in (302, 400)
