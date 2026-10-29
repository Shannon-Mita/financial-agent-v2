"""
Stage 0's one screen: both people see the household's current facts and
their freshness, and each can confirm/update only what §1 + Shannon's
amendments allow them to touch. Every write is checked server-side via
app.permissions.can_write_fact — never trust a hidden/disabled button.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required

from . import vendor_path  # noqa: F401
from facts_layer import Fact, Source, Unit, check_freshness

from .db import get_conn
from .permissions import can_write_fact, is_protected
from .store import PostgresFactStore

bp = Blueprint("routes", __name__)


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
        abort(404)
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
