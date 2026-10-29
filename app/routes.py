"""
Stage 0's one screen (both people see the household's current facts and
their freshness) plus Stage 1's goal/task screens. Every write is checked
server-side via app.permissions — never trust a hidden/disabled button.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import goals_store, vendor_path  # noqa: F401
from facts_layer import Fact, Source, Unit, check_freshness

from .db import get_conn
from .goal_progress import FIRE_TARGET_KEY, feasibility_for_goal, fire_accessible_breakdown
from .permissions import (
    CREATABLE_FACT_KEYS,
    FACT_BACKED_TARGET_DATE_KEYS,
    FACT_BACKED_TARGET_VALUE_KEYS,
    can_create_fact,
    can_create_task,
    can_edit_or_delete_task,
    can_toggle_goal_status,
    can_toggle_task,
    can_write_fact,
    is_protected,
    owner_required,
)
from .store import PostgresFactStore

bp = Blueprint("routes", __name__)


# Unit/category/owner for the handful of fact keys Stage 1 may create from
# scratch (no Stage 0 migration seeded them). Keep in lockstep with
# app.permissions.CREATABLE_FACT_KEYS — the create path is 403'd for any key
# missing from there before this dict is ever consulted.
CREATABLE_FACT_SPECS = {
    "goals.fire.target_date": (Unit.DATE, "goal", "joint"),
    "savings.house_deposit.balance": (Unit.GBP, "balance", "joint"),
}


def _store() -> PostgresFactStore:
    return PostgresFactStore(get_conn())


def _coerce_value(unit: Unit, raw: str):
    if unit == Unit.BOOL:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if unit in (Unit.GBP, Unit.COUNT):
        return int(raw)
    if unit in (Unit.GBP_PER_YEAR, Unit.GBP_PER_MONTH, Unit.PERCENT):
        return float(raw)
    return raw  # DATE (ISO string), TEXT


def _safe_next(default_endpoint, **default_kwargs):
    """Redirect target for goal/task POSTs — only ever one of our own
    /goals* paths (rendered by our own templates' hidden `next` field), not
    arbitrary client input, so no open-redirect risk."""
    nxt = request.form.get("next")
    if nxt and nxt.startswith("/goals"):
        return nxt
    return url_for(default_endpoint, **default_kwargs)


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
        fm = meta[key]
        rows.append({
            "key": key,
            "value": fm.fact.value,
            "unit": fm.fact.unit.value,
            "category": fm.fact.category,
            "owner": fm.owner,
            "as_of": fm.fact.as_of.isoformat(),
            "stale": key in stale_keys,
            "protected": is_protected(key),
            "can_edit": can_write_fact(current_user.role, fm.owner, key),
        })

    return render_template("dashboard.html", rows=rows, user=current_user)


@bp.route("/facts/<path:key>/confirm", methods=["POST"])
@login_required
def confirm_fact(key):
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
    return "", 204


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
            abort(400, description="Missing 'value'")
        unit, category, owner = CREATABLE_FACT_SPECS[key]
        new_fact = Fact.create(
            key=key, value=_coerce_value(unit, raw_value), unit=unit,
            source=Source.USER_STATED, category=category, as_of=date.today(),
        )
        store.set(new_fact, owner=owner, entered_by_user_id=int(current_user.id))
        return "", 204

    if not can_write_fact(current_user.role, fm.owner, key):
        abort(403)

    raw_value = request.form.get("value")
    if raw_value is None:
        abort(400, description="Missing 'value'")
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
    return "", 204


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
        g["feasibility"] = feasibility_for_goal(g, facts)

    fire_goal = next((g for g in goals if g["source_fact_key"] == FIRE_TARGET_KEY), None)
    fire_breakdown = fire_accessible_breakdown(facts) if fire_goal else None

    standalone_tasks = [t for t in goals_store.list_tasks(conn) if t["goal_id"] is None]
    users = {u["id"]: u for u in goals_store.list_users(conn)}

    return render_template(
        "goals_list.html", user=current_user,
        top_level_goals=by_parent[None], by_parent=by_parent,
        standalone_tasks=standalone_tasks, users=users,
        fire_breakdown=fire_breakdown,
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
        g["feasibility"] = feasibility_for_goal(g, facts)

    feasibility = feasibility_for_goal(goal, facts)
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
