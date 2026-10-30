"""
Live-site bug: updating property.main.mortgage_balance returns no error but
the displayed value doesn't change, even after a refresh. Other facts
update fine.

Investigation (via test fixtures only — no real data read):

(a) Does a new row get inserted? NO for a decimal input like "381150.09" —
    `_coerce_value`'s GBP branch is `int(raw)`, and `int("381150.09")`
    raises ValueError before any Fact is ever constructed, so `store.set()`
    is never reached. Confirmed by direct reproduction: `update_fact`
    catches that ValueError and currently redirects with an error flash
    ("isn't a valid value") — row count is unchanged, confirmed via a row
    count before/after. (In whatever version of this code was live when
    the bug was filed — before the try/except existed — the same
    ValueError was unhandled and surfaced as a bare 500, not caught.)

(b) current()/get()'s tie-break: both key off `entered_at` (microsecond
    TIMESTAMPTZ, confirmed via information_schema — no truncation), never
    `as_of`. Reproduced a forced exact-microsecond tie directly in the DB
    between two rows for this key, and PostgresFactStore.current()/get()
    both still returned the higher-id (later-inserted) row correctly. This
    is NOT the cause — ruled out.

(c) Value parsing: THIS is the cause. `property.main.mortgage_balance` is
    Unit.GBP, and a real mortgage balance naturally carries pence
    (381150.09, not 381150). `_coerce_value`'s GBP branch was `int(raw)`,
    which cannot parse ANY decimal string at all — it raised immediately,
    before rounding ever got a chance to happen. Every other fact a
    household normally updates by hand (salaries, spending, ISA balances)
    is typically entered as a whole number, so the same latent GBP-can't-
    accept-pence defect never surfaced for them — matching "other facts
    update fine" exactly.

    FIX: GBP now accepts pounds AND pence via `_parse_gbp` (app/routes.py)
    — not rounded away to whole pounds. 381150.09 stays 381150.09, stored
    rounded to 2 decimal places (never more, never truncated to an int).
"""
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

import re

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m
    return m.group(1)


def test_updating_mortgage_balance_with_a_pence_value_actually_updates_it(client, pg_conn, owner_user_id):
    """The failing reproduction: same key, same fact type/unit as the real
    curated field (Unit.GBP, category 'mortgage'), a realistic pre-existing
    balance, and a new value shaped like a real mortgage statement
    (381150.09) submitted through the real /facts/<key>/update route."""
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("property.main.mortgage_balance", 375000, Unit.GBP, Source.USER_STATED, "mortgage"),
        owner="joint", entered_by_user_id=owner_user_id,
    )

    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM facts WHERE key = 'property.main.mortgage_balance'")
        rows_before = cur.fetchone()[0]
    assert rows_before == 1

    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/property.main.mortgage_balance/update",
        data={"value": "381150.09", "next": "/", "csrf_token": token(page)},
    )

    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM facts WHERE key = 'property.main.mortgage_balance'")
        rows_after = cur.fetchone()[0]

    # (a) a new row must actually be inserted — the update must really happen.
    assert rows_after == rows_before + 1, (
        f"expected a new fact row to be written; row count was {rows_before} "
        f"before and {rows_after} after — the update was silently dropped"
    )

    # The displayed value must reflect the update, not the stale old one —
    # this is the literal symptom: "the displayed value doesn't change,
    # even after a refresh". Pence are kept, not rounded away to a whole pound.
    updated = store.get("property.main.mortgage_balance")
    assert updated.value == 381150.09, (
        f"expected the mortgage balance to update to 381150.09 (pence kept, "
        f"not rounded to a whole pound), got {updated.value!r} — looks like "
        f"the old value is still what's being shown"
    )
    assert resp.status_code == 303  # success, not an error response
