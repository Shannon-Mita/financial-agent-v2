"""
Live-site bug: GET /facts/income.shannon.bonus_expected/confirm (POST-only)
returned 405.

Audit (1): every <a href> on every page we render (Numbers, Goals, goal
detail, confirm-stale, both delete-confirm pages), as owner AND member.
RESULT: clean. Every rendered <a href> in every template points at a
GET-capable route — this part of the investigation did NOT find the cause.

Audit (2) — THE CAUSE: every redirect this app can produce is built from
either (a) a hardcoded url_for(...) to a known GET route (always safe), or
(b) a client-supplied `next` form field, validated by one of two functions:

  - _safe_relative_path() (used by the facts confirm/update routes and the
    confirm-stale walkthrough's _fact_redirect_target)
  - _safe_next() (used by the goal/task routes)

Both used to check ONLY "is this a same-site path" (an open-redirect
guard) — neither checked whether the target route actually accepts GET.
A `next` value that happened to BE a POST-only path (e.g. another fact's
/confirm or /update URL, /goals/<id>/delete, /goals/<id>/status, or any
/tasks/... action) sailed through validation untouched, and the resulting
303/302 redirect sent the browser's follow-up GET straight at a route that
only accepts POST — exactly the reported 405.

FIXED: both functions now also call _get_allowed() (app/routes.py), which
resolves the candidate path against the app's own url_map with method GET
and rejects it — falling back to the safe default — unless that GET
actually matches a real view (not 404, not 405, not an internal redirect).
test_redirect_target_validation.py covers the validators directly and
exhaustively; the two tests below re-run the exact crafted inputs that used
to reproduce the live 405 and confirm they now fall back safely instead.
"""
import re

import pytest
from werkzeug.exceptions import MethodNotAllowed

import app.goals_store as goals_store
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
HREF_RE = re.compile(r'href="([^"]+)"')
NEXT_INPUT_RE = re.compile(r'name="next" value="([^"]*)"')


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m
    return m.group(1)


def get_allowed(app, path):
    """Delegates to the real app.routes._get_allowed — one source of truth
    for "is this a safe redirect target", not a parallel re-implementation
    that could silently drift from what the app itself actually enforces."""
    from app.routes import _get_allowed

    with app.app_context():
        return _get_allowed(path)


def _seed_fixture(pg_conn, owner_id, member_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.bonus_expected", 2000, Unit.GBP, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_id,
    )
    goal_id = goals_store.create_goal(
        pg_conn, title="House deposit", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[member_id], user_id=owner_id,
    )
    task_id = goals_store.create_task(
        pg_conn, title="Open a LISA", goal_id=goal_id, assignee_user_id=member_id, user_id=owner_id,
    )
    return goal_id, task_id


# ── Audit (1): every <a href> on every page, owner and member — clean ────

PAGES = [
    "/",
    "/goals",
    "/confirm-stale",
]
OWNER_ONLY_PAGES = [
    "/goals/{goal_id}",
    "/goals/{goal_id}/delete-confirm",
    "/tasks/{task_id}/delete-confirm",
]


def _render_every_page(client, goal_id, task_id, owner_user_id, member_user_id):
    """Yields (role, path, rendered_body) for every page this app has, as
    both owner and member — the one shared crawl both audits below run
    over, so "every page" means the same set of pages in both places."""
    for role, user_id in (("owner", owner_user_id), ("member", member_user_id)):
        login(client, user_id)
        pages = list(PAGES)
        if role == "owner":
            pages += [p.format(goal_id=goal_id, task_id=task_id) for p in OWNER_ONLY_PAGES]
        else:
            pages += [f"/goals/{goal_id}"]  # member can view, not delete-confirm (403 anyway)

        for path in pages:
            resp = client.get(path)
            if resp.status_code == 200:
                yield role, path, resp.data.decode()


def test_no_rendered_link_points_at_a_post_only_route(app, client, pg_conn, owner_user_id, member_user_id):
    goal_id, task_id = _seed_fixture(pg_conn, owner_user_id, member_user_id)
    offenders = []

    for role, path, body in _render_every_page(client, goal_id, task_id, owner_user_id, member_user_id):
        for href in HREF_RE.findall(body):
            if not href.startswith("/"):
                continue  # static/manifest external-ish refs, not a navigation concern here
            clean_path = href.split("#")[0].split("?")[0]
            if not get_allowed(app, clean_path):
                offenders.append((role, path, href))

    assert offenders == [], f"found <a href> pointing at a POST-only route: {offenders}"


def test_no_rendered_hidden_next_input_points_at_a_post_only_route(
    app, client, pg_conn, owner_user_id, member_user_id
):
    """Every <form>'s hidden `next` field, on every page, as both owner and
    member — not just the links. This is the field that actually drives
    the redirect after a POST; the <a href> audit above doesn't touch it
    at all. If any page can emit a `next` value that isn't GET-capable,
    report exactly which page and which value, before fixing anything."""
    goal_id, task_id = _seed_fixture(pg_conn, owner_user_id, member_user_id)
    offenders = []

    for role, path, body in _render_every_page(client, goal_id, task_id, owner_user_id, member_user_id):
        for next_value in NEXT_INPUT_RE.findall(body):
            clean_path = next_value.split("#")[0].split("?")[0]
            if not get_allowed(app, clean_path):
                offenders.append((role, path, next_value))

    assert offenders == [], (
        f"found a hidden `next` input that isn't GET-capable: {offenders}"
    )


def test_no_code_path_derives_next_from_the_request_itself():
    """The code must never build a `next`/redirect target from
    request.path, request.url, or request.referrer — those reflect the
    CURRENT (often POST) request, so a naive `next = request.path` default
    would hand back exactly this app's own POST-only URL as the redirect
    target. Grepping source, not just testing behaviour, because this is a
    "never do this at all" rule, not a value to validate after the fact."""
    import os

    app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    offenders = []
    for root, _dirs, files in os.walk(app_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path) as f:
                lines = f.readlines()
            for lineno, line in enumerate(lines, 1):
                code = line.split("#", 1)[0]  # ignore comments — this is a
                # code-usage check, not a "never even mention it in prose" one
                for needle in ("request.path", "request.url", "request.referrer"):
                    if needle in code:
                        offenders.append((path, lineno, needle))

    assert offenders == [], f"found request-derived redirect input: {offenders}"


# ── Audit (2): the cause, NOW FIXED — _safe_relative_path/_safe_next also ──
# ── require the matched route to accept GET (app/routes.py::_get_allowed) ──

def test_fact_next_crafted_to_a_post_only_fact_url_now_falls_back_safely(app, client, pg_conn, owner_user_id):
    """Same crafted input that used to reproduce the live-site 405 — a
    fact's /confirm with `next` set to a DIFFERENT fact's /confirm URL
    (itself POST-only). _safe_relative_path now rejects it and falls back
    to the Numbers page; following the redirect lands on a real 200."""
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    store.set(
        Fact.create("income.shannon.bonus_expected", 2000, Unit.GBP, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")

    crafted_next = "/facts/income.shannon.bonus_expected/confirm"
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": crafted_next, "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    location = resp.headers["Location"]
    assert not location.startswith(crafted_next), (
        f"_safe_relative_path still let a POST-only path through: {location!r}"
    )
    assert location == "/#fact-income.shannon.paye_salary"  # fell back to the Numbers page

    final = client.get(location.split("#")[0])
    assert final.status_code == 200


def test_goal_next_crafted_to_a_post_only_goal_url_now_falls_back_safely(client, pg_conn, owner_user_id, member_user_id):
    """Same for _safe_next (goal/task flows): a crafted `next` of
    /goals/<id>/status (POST-only, but '/goals'-prefixed so the old prefix
    check alone let it through) now falls back to /goals."""
    goal_id, task_id = _seed_fixture(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    page = client.get(f"/goals/{goal_id}")

    crafted_next = f"/goals/{goal_id}/status"
    resp = client.post(
        f"/tasks/{task_id}/toggle",
        data={"next": crafted_next, "csrf_token": token(page)},
    )
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location != crafted_next
    assert location == "/goals"

    final = client.get(location)
    assert final.status_code == 200


@pytest.mark.parametrize("path", [
    "/facts/income.shannon.bonus_expected/confirm",
    "/facts/income.shannon.bonus_expected/update",
    "/goals/1/delete",
    "/goals/1/status",
    "/tasks",
    "/tasks/1/edit",
    "/tasks/1/delete",
    "/tasks/1/toggle",
    "/logout",
])
def test_these_specific_paths_really_are_405_on_get(app, path):
    """Confirms the exact shape of the live-site symptom independent of
    any particular key/id — a GET to any of these registered-but-POST-only
    paths 405s, regardless of whether the resource referenced exists."""
    assert get_allowed(app, path) is False
