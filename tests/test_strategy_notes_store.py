"""
Tests for app/strategy_notes_store.py — plain parameterised SQL store for
append-only notes on strategies and strategy steps (migrations/
005_strategy_notes.sql). No update/delete functions here, matching the
DB-level trigger that blocks those statements outright (same idiom as
app/decision_log_store.py — there is nothing to call). Needs a real
Postgres (skips without TEST_DATABASE_URL).
"""
import app.strategies_store as strategies_store
import app.strategy_notes_store as strategy_notes_store


def _make_strategy(pg_conn, owner_user_id, title="Strategy"):
    return strategies_store.create_strategy(
        pg_conn, title=title, detail="", area="Business", status="idea",
        work_lives_in="here", source="shannon",
        effect_on_net_worth=None, effect_on_passive_income=None,
        risks_childcare_eligibility="unknown", from_when=None, user_id=owner_user_id,
    )


def test_create_note_returns_an_id(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    note_id = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="Looked into this.", link=None,
        user_id=owner_user_id,
    )
    assert note_id is not None


def test_create_note_writes_an_audit_log_row(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    note_id = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="Looked into this.", link=None,
        user_id=owner_user_id,
    )
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT entity_type, entity_id, event_type, changed_by_user_id FROM audit_log WHERE entity_id = %s",
            (note_id,),
        )
        row = cur.fetchone()
    assert row == ("strategy_note", note_id, "created", owner_user_id)


def test_list_notes_for_strategy_is_newest_first(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    older = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="Older note", link=None, user_id=owner_user_id,
    )
    newer = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="Newer note", link=None, user_id=owner_user_id,
    )
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    ids_in_order = [n["id"] for n in notes]
    assert ids_in_order.index(newer) < ids_in_order.index(older)


def test_list_notes_for_strategy_includes_step_scoped_notes(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Do the thing", assignee_user_id=None, user_id=owner_user_id,
    )
    note_id = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=step_id, body="Pinned to the step.", link=None,
        user_id=owner_user_id,
    )
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    assert [n["id"] for n in notes] == [note_id]
    assert notes[0]["step_id"] == step_id


def test_list_notes_for_strategy_only_returns_that_strategys_notes(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id, title="A")
    other_strategy_id = _make_strategy(pg_conn, owner_user_id, title="B")
    note_id = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="For A", link=None, user_id=owner_user_id,
    )
    strategy_notes_store.create_note(
        pg_conn, strategy_id=other_strategy_id, step_id=None, body="For B", link=None, user_id=owner_user_id,
    )
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    assert [n["id"] for n in notes] == [note_id]


def test_create_note_with_a_link(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    note_id = strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="See this.",
        link="https://example.com/research", user_id=owner_user_id,
    )
    notes = strategy_notes_store.list_notes_for_strategy(pg_conn, strategy_id)
    assert [n for n in notes if n["id"] == note_id][0]["link"] == "https://example.com/research"


def test_strategy_has_notes_is_false_with_none(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    assert strategy_notes_store.strategy_has_notes(pg_conn, strategy_id) is False


def test_strategy_has_notes_is_true_once_one_exists(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=None, body="Note", link=None, user_id=owner_user_id,
    )
    assert strategy_notes_store.strategy_has_notes(pg_conn, strategy_id) is True


def test_step_has_notes_is_false_with_none(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Step", assignee_user_id=None, user_id=owner_user_id,
    )
    assert strategy_notes_store.step_has_notes(pg_conn, step_id) is False


def test_step_has_notes_is_true_once_one_is_pinned_to_it(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_id = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="Step", assignee_user_id=None, user_id=owner_user_id,
    )
    strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=step_id, body="Pinned", link=None, user_id=owner_user_id,
    )
    assert strategy_notes_store.step_has_notes(pg_conn, step_id) is True


def test_step_has_notes_is_false_for_a_different_steps_note(pg_conn, owner_user_id):
    strategy_id = _make_strategy(pg_conn, owner_user_id)
    step_a = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="A", assignee_user_id=None, user_id=owner_user_id,
    )
    step_b = strategies_store.create_strategy_step(
        pg_conn, strategy_id=strategy_id, title="B", assignee_user_id=None, user_id=owner_user_id,
    )
    strategy_notes_store.create_note(
        pg_conn, strategy_id=strategy_id, step_id=step_a, body="For A", link=None, user_id=owner_user_id,
    )
    assert strategy_notes_store.step_has_notes(pg_conn, step_b) is False
