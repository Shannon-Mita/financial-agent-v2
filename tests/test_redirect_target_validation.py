"""
B fix: _safe_relative_path and _safe_next must reject any `next` whose path
doesn't resolve to a GET-capable route — not just check "same-site". No DB
needed; these are pure functions once given an app context (they consult
current_app.url_map).
"""
import pytest

from app.routes import _safe_next, _safe_relative_path


@pytest.fixture
def ctx(app):
    with app.test_request_context():
        yield


POST_ONLY_PATHS = [
    "/facts/income.shannon.bonus_expected/confirm",
    "/facts/income.shannon.bonus_expected/update",
    "/confirm-stale/income.shannon.bonus_expected/confirm",
    "/confirm-stale/income.shannon.bonus_expected/update",
    "/goals",            # POST (create) — but see test below, has a GET too
    "/goals/1/delete",
    "/goals/1/status",
    "/tasks",
    "/tasks/1/edit",
    "/tasks/1/delete",
    "/tasks/1/toggle",
    "/logout",
]

# Paths that LOOK like they might be risky but genuinely have a GET sibling
# at the exact same URL — these must still be ALLOWED through.
GET_CAPABLE_PATHS = [
    "/",
    "/goals",
    "/goals/1",
    "/goals/1/edit",
    "/confirm-stale",
]


@pytest.mark.parametrize("path", [p for p in POST_ONLY_PATHS if p != "/goals"])
def test_safe_relative_path_rejects_every_post_only_route(ctx, path):
    assert _safe_relative_path(path) is None


def test_safe_relative_path_allows_goals_create_path_since_it_has_a_get_sibling(ctx):
    # /goals is POST (create) AND GET (list) at the identical path — a next
    # of "/goals" must still work, it's not actually a 405 trap.
    assert _safe_relative_path("/goals") == "/goals"


@pytest.mark.parametrize("path", GET_CAPABLE_PATHS)
def test_safe_relative_path_allows_real_get_capable_paths(ctx, path):
    assert _safe_relative_path(path) == path


def test_safe_relative_path_rejects_a_path_matching_no_route_at_all(ctx):
    assert _safe_relative_path("/this/route/does/not/exist") is None


def test_safe_relative_path_rejects_a_path_that_would_redirect(ctx):
    # Werkzeug's strict_slashes: a trailing slash where the rule has none
    # triggers an internal redirect rather than a direct match.
    assert _safe_relative_path("/goals/") is None


def test_safe_relative_path_strips_query_and_fragment_before_matching(ctx):
    assert _safe_relative_path("/goals/1/delete?x=1") is None
    assert _safe_relative_path("/goals/1/delete#y") is None
    assert _safe_relative_path("/goals/1?x=1") == "/goals/1?x=1"


@pytest.mark.parametrize("path", ["/goals/1/delete", "/goals/1/status"])
def test_safe_next_rejects_goals_post_only_sub_paths_via_form(app, path):
    with app.test_request_context("/tasks/1/toggle", method="POST", data={"next": path}):
        assert _safe_next("routes.goals_list") == "/goals"  # falls back to default


def test_safe_next_allows_a_real_goal_detail_path_via_form(app):
    with app.test_request_context("/tasks/1/toggle", method="POST", data={"next": "/goals/1"}):
        assert _safe_next("routes.goals_list") == "/goals/1"


def test_safe_next_falls_back_when_next_is_missing(app):
    with app.test_request_context("/tasks/1/toggle", method="POST", data={}):
        assert _safe_next("routes.goals_list") == "/goals"
