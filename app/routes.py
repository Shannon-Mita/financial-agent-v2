"""
Stage 0's one screen (both people see the household's current facts and
their freshness) plus Stage 1's goal/task screens. Every write is checked
server-side via app.permissions — never trust a hidden/disabled button.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

from . import decision_log_store, goals_store, strategies_store, vendor_path  # noqa: F401
from facts_layer import Fact, Source, Unit, check_freshness

from .db import get_conn
from .fact_labels import FACT_LABELS, GROUP_ORDER, HIDDEN_KEYS, group_for, label_for
from .goal_progress import (
    FIRE_TARGET_KEY,
    NET_WORTH_TARGET_AMOUNT_KEY,
    PASSIVE_INCOME_TARGET_AMOUNT_KEY,
    feasibility_for_goal,
    fire_accessible_breakdown,
    household_surplus,
    net_worth_feasibility,
    passive_income_feasibility,
)
from .permissions import (
    CREATABLE_FACT_KEYS,
    FACT_BACKED_TARGET_DATE_KEYS,
    FACT_BACKED_TARGET_VALUE_KEYS,
    can_archive_or_delete_strategy,
    can_create_fact,
    can_create_task,
    can_edit_or_delete_task,
    can_edit_strategy,
    can_set_strategy_status,
    can_toggle_goal_status,
    can_toggle_strategy_step,
    can_toggle_task,
    can_write_fact,
    is_protected,
    owner_required,
)
from .store import PostgresFactStore
from .strategy_review import is_strategy_stale

STRATEGY_AREAS = ("Work and income", "Relocation", "Business", "Investing", "Property", "Spending")

bp = Blueprint("routes", __name__)


# Unit/category/owner for the handful of fact keys Stage 1 may create from
# scratch (no Stage 0 migration seeded them). Keep in lockstep with
# app.permissions.CREATABLE_FACT_KEYS — the create path is 403'd for any key
# missing from there before this dict is ever consulted.
CREATABLE_FACT_SPECS = {
    "goals.fire.target_date": (Unit.DATE, "goal", "joint"),
    "savings.house_deposit.balance": (Unit.GBP, "balance", "joint"),
    "children.0.funded_childcare_30hrs_claiming": (Unit.BOOL, "profile", "joint"),
    "income.passive.rental": (Unit.GBP_PER_MONTH, "passive_income", "joint"),
    "income.passive.business": (Unit.GBP_PER_MONTH, "passive_income", "joint"),
    "income.passive.investments": (Unit.GBP_PER_MONTH, "passive_income", "joint"),
    "goals.net_worth.target_date": (Unit.DATE, "goal", "joint"),
    "goals.passive_income.target_amount": (Unit.GBP_PER_MONTH, "goal", "joint"),
    "goals.passive_income.target_date": (Unit.DATE, "goal", "joint"),
}


def _store() -> PostgresFactStore:
    return PostgresFactStore(get_conn())


def _parse_gbp(raw: str) -> float:
    """Pounds AND pence — not whole pounds. A real mortgage balance (or any
    money fact) naturally carries pence, e.g. 381150.09. Accepts a leading
    £, surrounding whitespace, and thousands commas (a human typing
    '£381,150.09' or ' 22000 ' means the same thing as '381150.09'), but
    never silently accepts something that isn't a real, sane amount of
    money — NaN, +/-inf, and negative amounts all raise, not round away to
    something plausible-looking. Stored rounded to 2 decimal places, since
    a third decimal place of a pound amount isn't a real penny."""
    cleaned = raw.strip()
    if cleaned.startswith("£"):
        cleaned = cleaned[1:]
    cleaned = cleaned.replace(",", "").strip()
    value = float(cleaned)  # raises ValueError for 'abc', '', etc.
    if not math.isfinite(value):
        raise ValueError(f"not a finite amount: {raw!r}")
    if value < 0:
        raise ValueError(f"negative amount not allowed: {raw!r}")
    return round(value, 2)


def _coerce_value(unit: Unit, raw: str):
    if unit == Unit.BOOL:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if unit == Unit.GBP:
        return _parse_gbp(raw)
    if unit == Unit.COUNT:
        return int(raw)
    if unit in (Unit.GBP_PER_YEAR, Unit.GBP_PER_MONTH, Unit.PERCENT):
        return float(raw)
    return raw  # DATE (ISO string), TEXT


def _get_allowed(path: str) -> bool:
    """True only if a GET to this exact path would be routed straight to a
    real view — False for a path that matches no route at all, matches
    only non-GET methods (the 405 this whole check exists to prevent), or
    would need an internal redirect to match (e.g. a strict-slashes
    trailing-slash mismatch) — none of those are a redirect target we
    should ever hand a browser as the follow-up to a POST."""
    adapter = current_app.url_map.bind(current_app.config.get("SERVER_NAME") or "localhost")
    try:
        adapter.match(path, method="GET")
        return True
    except (MethodNotAllowed, NotFound, RequestRedirect):
        return False


def _safe_next(default_endpoint, **default_kwargs):
    """Redirect target for goal/task POSTs — only ever one of our own
    /goals* paths (rendered by our own templates' hidden `next` field), not
    arbitrary client input, so no open-redirect risk — AND the matched
    route must actually accept GET, or a browser following this redirect
    would 405 (e.g. a crafted next of /goals/<id>/delete or /goals/<id>/status,
    both POST-only but '/goals'-prefixed)."""
    nxt = request.form.get("next")
    if nxt and nxt.startswith("/goals"):
        path_only = nxt.split("#", 1)[0].split("?", 1)[0]
        if _get_allowed(path_only):
            return nxt
    return url_for(default_endpoint, **default_kwargs)


def _safe_relative_path(raw: str | None) -> str | None:
    """A same-site relative path only: exactly one leading '/', never '//'
    or '/\\' (both of which some browsers treat as protocol-relative, i.e.
    an open redirect to another host), and never a full URL — AND the
    matched route must actually accept GET, or a browser following the
    redirect we build from this would 405 (e.g. a crafted next of another
    fact's /confirm or /update URL, or any other POST-only route). Returns
    None if `raw` doesn't satisfy all of that, so the caller falls back to
    a known-safe default instead of ever trusting arbitrary client input
    verbatim."""
    if not raw:
        return None
    if not raw.startswith("/"):
        return None
    if raw.startswith("//") or raw.startswith("/\\"):
        return None
    if "://" in raw:
        return None
    path_only = raw.split("#", 1)[0].split("?", 1)[0]
    if not _get_allowed(path_only):
        return None
    return raw


def _fact_redirect_target(key: str) -> str:
    """Validated `next` (falling back to the Numbers page) plus an anchor
    to the fact's own card, so a plain HTTP redirect (no JS at all) both
    returns to where the form was submitted from AND scrolls that fact's
    card into view — the browser's native #fragment handling does the
    scrolling, nothing server-side needed beyond the anchor existing in
    the HTML (see dashboard.html / confirm_stale.html's `id="fact-<key>"`)."""
    target = _safe_relative_path(request.form.get("next")) or url_for("routes.dashboard")
    return f"{target}#fact-{key}"


def _input_type_for_unit(unit: Unit) -> str:
    if unit == Unit.DATE:
        return "date"
    if unit in (Unit.GBP, Unit.COUNT, Unit.GBP_PER_YEAR, Unit.GBP_PER_MONTH, Unit.PERCENT):
        return "number"
    return "text"


@bp.route("/")
@login_required
def dashboard():
    store = _store()
    current = store.current()
    meta = store.current_with_meta()
    freshness = check_freshness(current, list(current.keys()))
    stale_keys = {sf.key for sf in freshness.stale}

    rows = []
    for key in sorted(current.keys()):
        if key in HIDDEN_KEYS:
            continue
        fm = meta[key]
        rows.append({
            "key": key,
            "label": label_for(key),
            "value": fm.fact.value,
            "unit": fm.fact.unit.value,
            "category": fm.fact.category,
            "owner": fm.owner,
            "as_of": fm.fact.as_of.isoformat(),
            "stale": key in stale_keys,
            "protected": is_protected(key),
            "can_edit": can_write_fact(current_user.role, fm.owner, key),
        })

    rows_by_group = defaultdict(list)
    for row in rows:
        rows_by_group[group_for(row["category"])].append(row)
    groups = [(g, rows_by_group[g]) for g in GROUP_ORDER if rows_by_group[g]]

    # Per-key, not a blanket owner-only gate — MEMBER_CREATABLE_FACT_KEYS
    # (the three passive income boxes) means a member can create some of
    # these too (Shannon, 2 Nov 2026); each key is still checked against
    # can_create_fact individually, never shown to someone who can't act
    # on it.
    not_yet_set = []
    for key in sorted(CREATABLE_FACT_KEYS):
        if key in current or key in HIDDEN_KEYS:
            continue
        if not can_create_fact(current_user.role, key):
            continue
        unit, _category, _owner = CREATABLE_FACT_SPECS[key]
        not_yet_set.append({
            "key": key,
            "unit": unit.value,
            "input_type": _input_type_for_unit(unit),
        })

    return render_template("dashboard.html", groups=groups, user=current_user, not_yet_set=not_yet_set)


def _confirm_fact_value(key: str) -> None:
    """Shared by /facts/<key>/confirm and the confirm-stale walkthrough —
    same permission check, same write, just two different response shapes
    (204 for the Stage 0 dashboard's no-navigate trick, a redirect for the
    walkthrough)."""
    store = _store()
    fm = store.get_meta(key)
    if fm is None:
        abort(404)
    if not can_write_fact(current_user.role, fm.owner, key):
        abort(403)

    new_fact = Fact.create(
        key=key,
        value=fm.fact.value,
        unit=fm.fact.unit,
        source=fm.fact.source,
        category=fm.fact.category,
        as_of=date.today(),
        note=fm.fact.note,
    )
    store.set(new_fact, owner=fm.owner, entered_by_user_id=int(current_user.id))


def _update_existing_fact_value(key: str, raw_value: str) -> None:
    """Shared by /facts/<key>/update's existing-key branch and the
    confirm-stale walkthrough's Edit action. Never handles create-if-missing
    — a stale fact, by definition, already exists."""
    store = _store()
    fm = store.get_meta(key)
    if fm is None:
        abort(404)
    if not can_write_fact(current_user.role, fm.owner, key):
        abort(403)

    value = _coerce_value(fm.fact.unit, raw_value)
    new_fact = Fact.create(
        key=key,
        value=value,
        unit=fm.fact.unit,
        source=Source.USER_STATED,
        category=fm.fact.category,
        as_of=date.today(),
    )
    store.set(new_fact, owner=fm.owner, entered_by_user_id=int(current_user.id))


def _flash_fact(message: str, level: str, key: str) -> None:
    """Encodes which fact a flash belongs to into the category (parsed back
    apart in base.html/dashboard.html/confirm_stale.html), so the message
    can be shown both in the sticky top banner AND inside that fact's own
    card — the anchor scroll lands you on the card, so the message needs
    to actually be there too, not just at the top where it's easy to miss
    having already scrolled past."""
    flash(message, f"{level}|fact|{key}")


@bp.route("/facts/<path:key>/confirm", methods=["POST"])
@login_required
def confirm_fact(key):
    # Permission/existence failures (404/403) are NOT validation failures —
    # they stay hard aborts, never redirected, so a disallowed write still
    # fails loudly rather than silently bouncing back with a vague flash.
    _confirm_fact_value(key)
    _flash_fact("Confirmed", "success", key)
    return redirect(_fact_redirect_target(key), code=303)


@bp.route("/facts/<path:key>/update", methods=["POST"])
@login_required
def update_fact(key):
    store = _store()
    fm = store.get_meta(key)

    if fm is None:
        # Create-if-missing is limited to a curated registry (CREATABLE_FACT_KEYS)
        # — an unknown key is 404, not 403: it isn't a thing that exists or could
        # be brought into existence via this endpoint, regardless of role.
        if key not in CREATABLE_FACT_KEYS:
            abort(404)
        if not can_create_fact(current_user.role, key):
            abort(403)
        raw_value = request.form.get("value")
        if raw_value is None:
            _flash_fact(f"Couldn't set {key}: a value is required.", "error", key)
            return redirect(_fact_redirect_target(key), code=303)
        unit, category, owner = CREATABLE_FACT_SPECS[key]
        try:
            value = _coerce_value(unit, raw_value)
        except (ValueError, TypeError):
            _flash_fact(f"Couldn't set {key}: ‘{raw_value}’ isn't a valid value.", "error", key)
            return redirect(_fact_redirect_target(key), code=303)
        new_fact = Fact.create(
            key=key, value=value, unit=unit,
            source=Source.USER_STATED, category=category, as_of=date.today(),
        )
        store.set(new_fact, owner=owner, entered_by_user_id=int(current_user.id))
        _flash_fact("Saved", "success", key)
        return redirect(_fact_redirect_target(key), code=303)

    raw_value = request.form.get("value")
    if raw_value is None:
        _flash_fact(f"Couldn't update {key}: a value is required.", "error", key)
        return redirect(_fact_redirect_target(key), code=303)
    try:
        _update_existing_fact_value(key, raw_value)
    except (ValueError, TypeError):
        _flash_fact(f"Couldn't update {key}: ‘{raw_value}’ isn't a valid value.", "error", key)
        return redirect(_fact_redirect_target(key), code=303)
    _flash_fact("Saved", "success", key)
    return redirect(_fact_redirect_target(key), code=303)


# ─────────────────────────────────────────────────────────────────────────────
# Confirm-stale walkthrough — one stale fact at a time, Confirm or Edit.
# Uses the exact same can_write_fact gate as the Numbers page: a stale fact
# the current user isn't allowed to write never appears in their walkthrough
# at all (not shown-but-disabled — simply absent).
# ─────────────────────────────────────────────────────────────────────────────

def _actionable_stale_items():
    """Stale facts the current user may write, oldest-first (most overdue
    first), each with its label/age for the template."""
    store = _store()
    current = store.current()
    meta = store.current_with_meta()
    freshness = check_freshness(current, list(current.keys()))

    items = []
    for sf in freshness.stale:
        fm = meta[sf.key]
        if not can_write_fact(current_user.role, fm.owner, sf.key):
            continue
        items.append({
            "key": sf.key,
            "label": label_for(sf.key),
            "value": fm.fact.value,
            "unit": fm.fact.unit.value,
            "owner": fm.owner,
            "as_of": fm.fact.as_of.isoformat(),
            "age_days": sf.age_days,
            "max_age_days": sf.max_age_days,
        })
    items.sort(key=lambda i: -i["age_days"])
    return items


@bp.route("/confirm-stale")
@login_required
def confirm_stale():
    items = _actionable_stale_items()
    return render_template(
        "confirm_stale.html", user=current_user,
        item=items[0] if items else None, remaining=len(items),
    )


@bp.route("/confirm-stale/<path:key>/confirm", methods=["POST"])
@login_required
def confirm_stale_confirm(key):
    _confirm_fact_value(key)
    return redirect(url_for("routes.confirm_stale"))


@bp.route("/confirm-stale/<path:key>/update", methods=["POST"])
@login_required
def confirm_stale_update(key):
    raw_value = request.form.get("value")
    if raw_value is None:
        abort(400, description="Missing 'value'")
    _update_existing_fact_value(key, raw_value)
    return redirect(url_for("routes.confirm_stale"))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — goals
# ─────────────────────────────────────────────────────────────────────────────

def _parse_goal_form(form, known_fact_keys):
    """Shared by create/edit. Enforces 'never both' structurally: each of
    (target_value, source_fact_key) and (target_date, target_date_fact_key)
    is populated from exactly one radio-selected mode, never both — backed
    up by the DB CHECK constraints regardless."""
    title = (form.get("title") or "").strip()
    if not title:
        abort(400, description="Missing title")
    type_ = form.get("type")
    if type_ not in ("target", "binary", "habit"):
        abort(400, description="Invalid type")

    target_value = target_date = source_fact_key = target_date_fact_key = None
    cadence_period = cadence_amount = None

    if type_ == "target":
        value_mode = form.get("target_value_mode")
        if value_mode == "fact":
            source_fact_key = form.get("source_fact_key") or None
            if source_fact_key not in FACT_BACKED_TARGET_VALUE_KEYS:
                abort(400, description="Unknown fact-backed target key")
        elif value_mode == "amount":
            raw = form.get("target_value")
            if not raw:
                abort(400, description="Missing target_value")
            target_value = float(raw)
        else:
            abort(400, description="Missing target_value_mode")

        date_mode = form.get("target_date_mode")
        if date_mode == "fact":
            target_date_fact_key = form.get("target_date_fact_key") or None
            if target_date_fact_key not in FACT_BACKED_TARGET_DATE_KEYS:
                abort(400, description="Unknown fact-backed target date key")
        elif date_mode == "date":
            raw = form.get("target_date")
            if not raw:
                abort(400, description="Missing target_date")
            target_date = raw
        else:
            abort(400, description="Missing target_date_mode")

    elif type_ == "habit":
        cadence_period = form.get("cadence_period") or None
        if cadence_period not in ("weekly", "monthly"):
            abort(400, description="Invalid cadence_period")
        raw = form.get("cadence_amount")
        cadence_amount = float(raw) if raw else None

    progress_fact_keys = [k.strip() for k in (form.get("progress_fact_keys") or "").split(",") if k.strip()]
    for k in progress_fact_keys:
        if k not in known_fact_keys:
            abort(400, description=f"Unknown fact key: {k}")

    parent_id_raw = form.get("parent_id")
    parent_id = int(parent_id_raw) if parent_id_raw else None

    assignee_user_ids = [int(v) for v in form.getlist("assignee_user_ids")]

    fields = dict(
        title=title, type=type_, target_value=target_value, target_date=target_date,
        source_fact_key=source_fact_key, target_date_fact_key=target_date_fact_key,
        progress_fact_keys=progress_fact_keys or None, cadence_period=cadence_period,
        cadence_amount=cadence_amount, parent_id=parent_id,
    )
    return fields, assignee_user_ids


def _feasibility_for(goal: dict, facts: dict):
    """Net worth and passive income (Stage 2 Step 3) can't use the generic
    sum-only feasibility_for_goal() — net worth needs assets-minus-debts,
    passive income needs the stream-unit conversion — so they're dispatched
    to their own calculations. Every other goal (milestones, old FIRE goal
    if still present, anything else) keeps the generic one."""
    if goal["source_fact_key"] == NET_WORTH_TARGET_AMOUNT_KEY:
        return net_worth_feasibility(goal, facts)
    if goal["source_fact_key"] == PASSIVE_INCOME_TARGET_AMOUNT_KEY:
        return passive_income_feasibility(goal, facts)
    return feasibility_for_goal(goal, facts)


@bp.route("/goals")
@login_required
def goals_list():
    conn = get_conn()
    facts = _store().current()
    goals = goals_store.list_goals(conn)
    by_parent = defaultdict(list)
    for g in goals:
        by_parent[g["parent_id"]].append(g)
    for g in goals:
        g["feasibility"] = _feasibility_for(g, facts)

    # The two apex goals (Stage 2 Step 3) — net worth and passive income
    # replace FIRE as the apexes. If the old FIRE goal still exists
    # (Shannon deletes it himself), it now renders as an ordinary
    # top-level goal, not a third apex — the fire_breakdown card above is
    # unaffected and still shows for it specifically, until it's gone.
    fire_goal = next((g for g in goals if g["source_fact_key"] == FIRE_TARGET_KEY), None)
    fire_breakdown = fire_accessible_breakdown(facts) if fire_goal else None
    net_worth_goal = next((g for g in goals if g["source_fact_key"] == NET_WORTH_TARGET_AMOUNT_KEY), None)
    passive_income_goal = next((g for g in goals if g["source_fact_key"] == PASSIVE_INCOME_TARGET_AMOUNT_KEY), None)
    apex_goals = [g for g in (net_worth_goal, passive_income_goal) if g]
    apex_ids = {g["id"] for g in apex_goals}

    top_level_goals = by_parent[None]
    other_top_level_goals = [g for g in top_level_goals if g["id"] not in apex_ids]

    surplus_display = household_surplus(facts)

    standalone_tasks = [t for t in goals_store.list_tasks(conn) if t["goal_id"] is None]
    users = {u["id"]: u for u in goals_store.list_users(conn)}

    # Strategies grouped by area (§7) — archived strategies drop off this
    # active list and stay in history, reachable only by id.
    active_strategies = [s for s in strategies_store.list_strategies(conn) if s["status"] != "archived"]
    for s in active_strategies:
        s["stale"] = is_strategy_stale(s["last_reviewed_date"])
    strategies_by_area = defaultdict(list)
    for s in active_strategies:
        strategies_by_area[s["area"]].append(s)

    return render_template(
        "goals_list.html", user=current_user,
        apex_goals=apex_goals, other_top_level_goals=other_top_level_goals, by_parent=by_parent,
        standalone_tasks=standalone_tasks, users=users,
        fire_breakdown=fire_breakdown, surplus_display=surplus_display,
        strategy_areas=STRATEGY_AREAS, strategies_by_area=strategies_by_area,
    )


@bp.route("/goals/new")
@owner_required
def new_goal():
    conn = get_conn()
    return render_template(
        "goal_form.html", user=current_user, goal=None,
        users=goals_store.list_users(conn), goals=goals_store.list_goals(conn),
        fact_value_keys=sorted(FACT_BACKED_TARGET_VALUE_KEYS),
        fact_date_keys=sorted(FACT_BACKED_TARGET_DATE_KEYS),
    )


@bp.route("/goals", methods=["POST"])
@owner_required
def create_goal():
    conn = get_conn()
    known_keys = set(_store().current().keys())
    fields, assignee_user_ids = _parse_goal_form(request.form, known_keys)
    goal_id = goals_store.create_goal(
        conn, **fields, assignee_user_ids=assignee_user_ids, user_id=int(current_user.id),
    )
    return redirect(url_for("routes.goal_detail", goal_id=goal_id))


@bp.route("/goals/<int:goal_id>")
@login_required
def goal_detail(goal_id):
    conn = get_conn()
    goal = goals_store.get_goal(conn, goal_id)
    if goal is None:
        abort(404)
    facts = _store().current()
    users = {u["id"]: u for u in goals_store.list_users(conn)}

    sub_goals = [g for g in goals_store.list_goals(conn) if g["parent_id"] == goal_id]
    for g in sub_goals:
        g["feasibility"] = _feasibility_for(g, facts)

    feasibility = _feasibility_for(goal, facts)
    fire_breakdown = fire_accessible_breakdown(facts) if goal["source_fact_key"] == FIRE_TARGET_KEY else None

    tasks = goals_store.list_tasks(conn, goal_id=goal_id)
    can_toggle_status = can_toggle_goal_status(
        current_user.role, int(current_user.id), goal["type"], goal["assignee_user_ids"]
    )

    return render_template(
        "goal_detail.html", user=current_user, goal=goal, feasibility=feasibility,
        fire_breakdown=fire_breakdown, sub_goals=sub_goals, tasks=tasks, users=users,
        can_toggle_status=can_toggle_status,
        can_create_task=can_create_task(current_user.role, int(current_user.id), int(current_user.id)),
    )


@bp.route("/goals/<int:goal_id>/edit")
@owner_required
def edit_goal(goal_id):
    conn = get_conn()
    goal = goals_store.get_goal(conn, goal_id)
    if goal is None:
        abort(404)
    other_goals = [g for g in goals_store.list_goals(conn) if g["id"] != goal_id]
    return render_template(
        "goal_form.html", user=current_user, goal=goal,
        users=goals_store.list_users(conn), goals=other_goals,
        fact_value_keys=sorted(FACT_BACKED_TARGET_VALUE_KEYS),
        fact_date_keys=sorted(FACT_BACKED_TARGET_DATE_KEYS),
    )


@bp.route("/goals/<int:goal_id>/edit", methods=["POST"])
@owner_required
def update_goal(goal_id):
    conn = get_conn()
    if goals_store.get_goal(conn, goal_id) is None:
        abort(404)
    known_keys = set(_store().current().keys())
    fields, assignee_user_ids = _parse_goal_form(request.form, known_keys)
    goals_store.update_goal(conn, goal_id, fields, assignee_user_ids=assignee_user_ids, user_id=int(current_user.id))
    return redirect(url_for("routes.goal_detail", goal_id=goal_id))


@bp.route("/goals/<int:goal_id>/delete-confirm")
@owner_required
def goal_delete_confirm(goal_id):
    """Server-side confirmation page — the CSP forbids inline JS, so this
    replaces a client-side confirm() dialog with a real page: what would be
    deleted (the goal's own tasks are cascade-deleted with it), a Cancel
    link, and the actual delete button only when deletion is actually
    possible (blocked entirely while sub-goals still exist, same rule as
    the delete endpoint itself)."""
    conn = get_conn()
    goal = goals_store.get_goal(conn, goal_id)
    if goal is None:
        abort(404)
    blocked = goals_store.has_children(conn, goal_id)
    tasks = goals_store.list_tasks(conn, goal_id=goal_id)
    return render_template(
        "goal_delete_confirm.html", user=current_user, goal=goal, blocked=blocked, tasks=tasks,
    )


@bp.route("/goals/<int:goal_id>/delete", methods=["POST"])
@owner_required
def delete_goal(goal_id):
    conn = get_conn()
    if goals_store.get_goal(conn, goal_id) is None:
        abort(404)
    if goals_store.has_children(conn, goal_id):
        abort(400, description="Delete sub-goals first")
    goals_store.delete_goal(conn, goal_id, int(current_user.id))
    return redirect(url_for("routes.goals_list"))


@bp.route("/goals/<int:goal_id>/status", methods=["POST"])
@login_required
def toggle_goal_status(goal_id):
    conn = get_conn()
    goal = goals_store.get_goal(conn, goal_id)
    if goal is None:
        abort(404)
    if not can_toggle_goal_status(current_user.role, int(current_user.id), goal["type"], goal["assignee_user_ids"]):
        abort(403)
    new_status = "active" if goal["status"] == "done" else "done"
    goals_store.set_goal_status(conn, goal_id, new_status, int(current_user.id))
    return redirect(_safe_next("routes.goal_detail", goal_id=goal_id))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 Step 4 — strategies
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_STATUSES = ("idea", "in progress", "active", "parked", "archived")
RISKS_CHILDCARE_VALUES = ("yes", "no", "unknown")


def _coerce_optional_numeric(raw: str | None) -> float | None:
    """Blank = unknown, stored as NULL, never defaulted to zero. A real,
    known zero effect must be typed as "0" (Shannon, 1 Nov 2026)."""
    raw = (raw or "").strip()
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        abort(400, description=f"Not a number: {raw!r}")


def _parse_strategy_form(form) -> dict:
    title = (form.get("title") or "").strip()
    if not title:
        abort(400, description="Missing title")
    area = form.get("area")
    if area not in STRATEGY_AREAS:
        abort(400, description="Invalid area")
    status = form.get("status") or "idea"
    if status not in STRATEGY_STATUSES:
        abort(400, description="Invalid status")
    risks = form.get("risks_childcare_eligibility") or "unknown"
    if risks not in RISKS_CHILDCARE_VALUES:
        abort(400, description="Invalid risks_childcare_eligibility")
    return dict(
        title=title,
        detail=(form.get("detail") or "").strip(),
        area=area,
        status=status,
        work_lives_in=(form.get("work_lives_in") or "").strip(),
        effect_on_net_worth=_coerce_optional_numeric(form.get("effect_on_net_worth")),
        effect_on_passive_income=_coerce_optional_numeric(form.get("effect_on_passive_income")),
        risks_childcare_eligibility=risks,
        from_when=(form.get("from_when") or "").strip() or None,
    )


def _parse_lever_from_form(form, known_fact_keys: set) -> dict | None:
    """dimension validated app-side against the curated set of known fact
    keys (app/fact_labels.py) — facts have no per-key table row to foreign
    key against (Shannon, 1 Nov 2026: 'validated app-side against a
    curated set')."""
    dimension = (form.get("lever_dimension") or "").strip()
    if not dimension:
        return None
    if dimension not in known_fact_keys:
        abort(400, description=f"Unknown fact key for lever dimension: {dimension}")
    delta_raw = form.get("lever_delta")
    from_date = form.get("lever_from_date")
    if not delta_raw or not from_date:
        abort(400, description="Lever delta and from_date are required when a dimension is set")
    return {"dimension": dimension, "delta": float(delta_raw), "from_date": from_date}


@bp.route("/strategies/new")
@login_required
def new_strategy():
    if not can_edit_strategy(current_user.role):
        abort(403)
    conn = get_conn()
    return render_template(
        "strategy_form.html", user=current_user, strategy=None,
        goals=goals_store.list_goals(conn), linked_goal_ids=[],
        areas=STRATEGY_AREAS, statuses=STRATEGY_STATUSES, lever=None,
    )


@bp.route("/strategies", methods=["POST"])
@login_required
def create_strategy():
    if not can_edit_strategy(current_user.role):
        abort(403)
    new_status = request.form.get("status") or "idea"
    if not can_set_strategy_status(current_user.role, new_status):
        abort(403)
    conn = get_conn()
    fields = _parse_strategy_form(request.form)
    source = "shannon" if current_user.role == "owner" else "asha"
    strategy_id = strategies_store.create_strategy(conn, **fields, source=source, user_id=int(current_user.id))

    goal_ids = [int(v) for v in request.form.getlist("goal_ids")]
    strategies_store.set_strategy_goal_links(conn, strategy_id, goal_ids)

    lever = _parse_lever_from_form(request.form, set(FACT_LABELS.keys()))
    strategies_store.set_strategy_levers(conn, strategy_id, [lever] if lever else [])

    return redirect(url_for("routes.strategy_detail", strategy_id=strategy_id))


@bp.route("/strategies/<int:strategy_id>")
@login_required
def strategy_detail(strategy_id):
    conn = get_conn()
    strategy = strategies_store.get_strategy(conn, strategy_id)
    if strategy is None:
        abort(404)
    strategy["stale"] = is_strategy_stale(strategy["last_reviewed_date"])
    goal_ids = strategies_store.list_strategy_goal_ids(conn, strategy_id)
    goals_by_id = {g["id"]: g for g in goals_store.list_goals(conn)}
    linked_goals = [goals_by_id[gid] for gid in goal_ids if gid in goals_by_id]
    levers = strategies_store.list_strategy_levers(conn, strategy_id)
    steps = strategies_store.list_strategy_steps(conn, strategy_id)
    users = {u["id"]: u for u in goals_store.list_users(conn)}
    return render_template(
        "strategy_detail.html", user=current_user, strategy=strategy,
        linked_goals=linked_goals, levers=levers, steps=steps, users=users,
        can_edit=can_edit_strategy(current_user.role),
        can_archive_or_delete=can_archive_or_delete_strategy(current_user.role),
        can_toggle_step=lambda step: can_toggle_strategy_step(
            current_user.role, int(current_user.id), step["assignee_user_id"]
        ),
    )


@bp.route("/strategies/<int:strategy_id>/edit")
@login_required
def edit_strategy(strategy_id):
    if not can_edit_strategy(current_user.role):
        abort(403)
    conn = get_conn()
    strategy = strategies_store.get_strategy(conn, strategy_id)
    if strategy is None:
        abort(404)
    linked_goal_ids = strategies_store.list_strategy_goal_ids(conn, strategy_id)
    levers = strategies_store.list_strategy_levers(conn, strategy_id)
    return render_template(
        "strategy_form.html", user=current_user, strategy=strategy,
        goals=goals_store.list_goals(conn), linked_goal_ids=linked_goal_ids,
        areas=STRATEGY_AREAS, statuses=STRATEGY_STATUSES, lever=levers[0] if levers else None,
    )


@bp.route("/strategies/<int:strategy_id>/edit", methods=["POST"])
@login_required
def update_strategy(strategy_id):
    if not can_edit_strategy(current_user.role):
        abort(403)
    conn = get_conn()
    if strategies_store.get_strategy(conn, strategy_id) is None:
        abort(404)
    new_status = request.form.get("status") or "idea"
    if not can_set_strategy_status(current_user.role, new_status):
        abort(403)
    fields = _parse_strategy_form(request.form)
    fields["last_reviewed_date"] = request.form.get("last_reviewed_date") or None
    strategies_store.update_strategy(conn, strategy_id, fields, user_id=int(current_user.id))

    goal_ids = [int(v) for v in request.form.getlist("goal_ids")]
    strategies_store.set_strategy_goal_links(conn, strategy_id, goal_ids)

    lever = _parse_lever_from_form(request.form, set(FACT_LABELS.keys()))
    strategies_store.set_strategy_levers(conn, strategy_id, [lever] if lever else [])

    return redirect(url_for("routes.strategy_detail", strategy_id=strategy_id))


@bp.route("/strategies/<int:strategy_id>/archive-confirm")
@owner_required
def strategy_archive_confirm(strategy_id):
    conn = get_conn()
    strategy = strategies_store.get_strategy(conn, strategy_id)
    if strategy is None:
        abort(404)
    return render_template("strategy_archive_confirm.html", user=current_user, strategy=strategy)


@bp.route("/strategies/<int:strategy_id>/archive", methods=["POST"])
@owner_required
def archive_strategy(strategy_id):
    conn = get_conn()
    if strategies_store.get_strategy(conn, strategy_id) is None:
        abort(404)
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        abort(400, description="A reason is required to archive")
    strategies_store.archive_strategy(
        conn, strategy_id, reason=reason, archived_date=date.today(), user_id=int(current_user.id),
    )
    return redirect(url_for("routes.goals_list"))


@bp.route("/strategies/<int:strategy_id>/delete-confirm")
@owner_required
def strategy_delete_confirm(strategy_id):
    conn = get_conn()
    strategy = strategies_store.get_strategy(conn, strategy_id)
    if strategy is None:
        abort(404)
    steps = strategies_store.list_strategy_steps(conn, strategy_id)
    return render_template("strategy_delete_confirm.html", user=current_user, strategy=strategy, steps=steps)


@bp.route("/strategies/<int:strategy_id>/delete", methods=["POST"])
@owner_required
def delete_strategy(strategy_id):
    conn = get_conn()
    if strategies_store.get_strategy(conn, strategy_id) is None:
        abort(404)
    strategies_store.delete_strategy(conn, strategy_id, user_id=int(current_user.id))
    return redirect(url_for("routes.goals_list"))


# ── Strategy steps (mirrors tasks, different permissions) ───────────────

@bp.route("/strategy-steps", methods=["POST"])
@login_required
def create_strategy_step():
    if not can_edit_strategy(current_user.role):
        abort(403)
    strategy_id_raw = request.form.get("strategy_id")
    if not strategy_id_raw:
        abort(400, description="Missing strategy_id")
    strategy_id = int(strategy_id_raw)
    conn = get_conn()
    if strategies_store.get_strategy(conn, strategy_id) is None:
        abort(404)
    title = (request.form.get("title") or "").strip()
    if not title:
        abort(400, description="Missing title")
    assignee_raw = request.form.get("assignee_user_id")
    assignee_user_id = int(assignee_raw) if assignee_raw else None
    strategies_store.create_strategy_step(
        conn, strategy_id=strategy_id, title=title, assignee_user_id=assignee_user_id,
        user_id=int(current_user.id),
    )
    return redirect(_safe_next("routes.strategy_detail", strategy_id=strategy_id))


@bp.route("/strategy-steps/<int:step_id>/edit", methods=["POST"])
@login_required
def update_strategy_step(step_id):
    if not can_edit_strategy(current_user.role):
        abort(403)
    conn = get_conn()
    step = strategies_store.get_strategy_step(conn, step_id)
    if step is None:
        abort(404)
    title = (request.form.get("title") or "").strip()
    if not title:
        abort(400, description="Missing title")
    assignee_raw = request.form.get("assignee_user_id")
    assignee_user_id = int(assignee_raw) if assignee_raw else None
    strategies_store.update_strategy_step(
        conn, step_id, title=title, assignee_user_id=assignee_user_id, user_id=int(current_user.id),
    )
    return redirect(_safe_next("routes.strategy_detail", strategy_id=step["strategy_id"]))


@bp.route("/strategy-steps/<int:step_id>/delete", methods=["POST"])
@login_required
def delete_strategy_step(step_id):
    if not can_edit_strategy(current_user.role):
        abort(403)
    conn = get_conn()
    step = strategies_store.get_strategy_step(conn, step_id)
    if step is None:
        abort(404)
    strategies_store.delete_strategy_step(conn, step_id)
    return redirect(_safe_next("routes.strategy_detail", strategy_id=step["strategy_id"]))


@bp.route("/strategy-steps/<int:step_id>/toggle", methods=["POST"])
@login_required
def toggle_strategy_step(step_id):
    conn = get_conn()
    step = strategies_store.get_strategy_step(conn, step_id)
    if step is None:
        abort(404)
    if not can_toggle_strategy_step(current_user.role, int(current_user.id), step["assignee_user_id"]):
        abort(403)
    strategies_store.toggle_strategy_step(conn, step_id, not step["done"], int(current_user.id))
    return redirect(_safe_next("routes.strategy_detail", strategy_id=step["strategy_id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — tasks
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/tasks", methods=["POST"])
@login_required
def create_task():
    conn = get_conn()
    title = (request.form.get("title") or "").strip()
    if not title:
        abort(400, description="Missing title")
    goal_id_raw = request.form.get("goal_id")
    goal_id = int(goal_id_raw) if goal_id_raw else None
    assignee_raw = request.form.get("assignee_user_id")
    assignee_user_id = int(assignee_raw) if assignee_raw else None

    if not can_create_task(current_user.role, int(current_user.id), assignee_user_id):
        abort(403)

    goals_store.create_task(
        conn, title=title, goal_id=goal_id, assignee_user_id=assignee_user_id,
        user_id=int(current_user.id),
    )
    return redirect(_safe_next("routes.goals_list"))


@bp.route("/tasks/<int:task_id>/edit", methods=["POST"])
@login_required
def update_task(task_id):
    conn = get_conn()
    task = goals_store.get_task(conn, task_id)
    if task is None:
        abort(404)
    if not can_edit_or_delete_task(
        current_user.role, int(current_user.id), task["created_by_user_id"], task["assignee_user_id"]
    ):
        abort(403)

    title = (request.form.get("title") or "").strip()
    if not title:
        abort(400, description="Missing title")
    assignee_raw = request.form.get("assignee_user_id")
    assignee_user_id = int(assignee_raw) if assignee_raw else None

    goals_store.update_task(
        conn, task_id, title=title, assignee_user_id=assignee_user_id, user_id=int(current_user.id),
    )
    return redirect(_safe_next("routes.goals_list"))


@bp.route("/tasks/<int:task_id>/delete-confirm")
@login_required
def task_delete_confirm(task_id):
    conn = get_conn()
    task = goals_store.get_task(conn, task_id)
    if task is None:
        abort(404)
    if not can_edit_or_delete_task(
        current_user.role, int(current_user.id), task["created_by_user_id"], task["assignee_user_id"]
    ):
        abort(403)
    return render_template("task_delete_confirm.html", user=current_user, task=task)


@bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    conn = get_conn()
    task = goals_store.get_task(conn, task_id)
    if task is None:
        abort(404)
    if not can_edit_or_delete_task(
        current_user.role, int(current_user.id), task["created_by_user_id"], task["assignee_user_id"]
    ):
        abort(403)
    goals_store.delete_task(conn, task_id, int(current_user.id))
    return redirect(_safe_next("routes.goals_list"))


@bp.route("/tasks/<int:task_id>/toggle", methods=["POST"])
@login_required
def toggle_task(task_id):
    conn = get_conn()
    task = goals_store.get_task(conn, task_id)
    if task is None:
        abort(404)
    if not can_toggle_task(current_user.role, int(current_user.id), task["assignee_user_id"]):
        abort(403)
    goals_store.toggle_task(conn, task_id, not task["done"], int(current_user.id))
    return redirect(_safe_next("routes.goals_list"))


# ── Decision log — both can add, nobody can edit or delete ──────────────

def _parse_decision_form(form) -> dict:
    decision_date = form.get("decision_date")
    if not decision_date:
        abort(400, description="Missing decision_date")
    decision = (form.get("decision") or "").strip()
    if not decision:
        abort(400, description="Missing decision")
    reason = (form.get("reason") or "").strip()
    if not reason:
        abort(400, description="Missing reason")
    assumptions = (form.get("assumptions") or "").strip()
    return dict(decision_date=decision_date, decision=decision, reason=reason, assumptions=assumptions)


@bp.route("/decisions")
@login_required
def decisions_list():
    conn = get_conn()
    decisions = decision_log_store.list_decisions(conn)
    users = {u["id"]: u for u in goals_store.list_users(conn)}
    return render_template(
        "decisions_list.html", user=current_user, decisions=decisions, users=users,
        today=date.today().isoformat(),
    )


@bp.route("/decisions", methods=["POST"])
@login_required
def create_decision():
    fields = _parse_decision_form(request.form)
    conn = get_conn()
    decision_log_store.create_decision(conn, **fields, user_id=int(current_user.id))
    return redirect(url_for("routes.decisions_list"))
