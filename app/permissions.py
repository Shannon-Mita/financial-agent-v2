"""
Server-side permission rules (spec §1, plus Shannon's Stage 0/1 amendments).

Base rule: the owner role can write anything. The member role can write a
fact only if it's owned by `partner` or `joint` — UNLESS the key is in the
protected list, in which case it's owner-only even if the fact itself is
marked `joint` (the FIRE target and plan settings are never the partner's
to edit, regardless of whose numbers feed into them).
"""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"

VALID_FACT_OWNERS = ("shannon", "partner", "joint")

# Exact keys or dotted-prefixes that only the owner role may write, no matter
# which `owner` the fact itself is tagged with. Extend this list, don't bypass
# it, as new goal/plan keys are added.
#
# "goals." covers every migrated goal key (goals.fire.*, goals.net_worth.*,
# and any added later) — these load as owner=joint in Stage 0 but must stay
# owner-only to write, same rationale as fire.target/plan. above.
PROTECTED_KEY_PREFIXES = (
    "fire.target",
    "plan.",
    "goals.",
)


def is_protected(key: str) -> bool:
    return any(key == p or key.startswith(p) for p in PROTECTED_KEY_PREFIXES)


def can_write_fact(role: str, fact_owner: str, key: str) -> bool:
    """Server-side check — call this on every write endpoint, never trust
    the client. `role` is the authenticated user's role; `fact_owner` is the
    owner tagged on the fact being written (shannon/partner/joint)."""
    if role == ROLE_OWNER:
        return True
    if role != ROLE_MEMBER:
        return False
    if is_protected(key):
        return False
    return fact_owner in ("partner", "joint")


# Fact keys /facts/<key>/update may CREATE if the key has never been written
# before — curated, not freeform. Stage 1's goal facts (goals.fire.target_date,
# savings.house_deposit.balance) have no Stage 0 migration to seed them from,
# unlike every other fact the dashboard lists. Extend this set, don't bypass
# it, as new fact-backed goals are added.
CREATABLE_FACT_KEYS = frozenset({
    "goals.fire.target_date",
    "savings.house_deposit.balance",
})


# Fact keys a goal's `source_fact_key` / `target_date_fact_key` may point at
# (goal create/edit forms). Curated, not freeform — the whole point of
# fact-backing a goal's target is to point at a SPECIFIC known number
# (the FIRE target), not let the owner wire up any arbitrary fact. Extend
# this set, don't bypass it, if another fact-backed goal is approved.
FACT_BACKED_TARGET_VALUE_KEYS = frozenset({"goals.fire.target_number"})
FACT_BACKED_TARGET_DATE_KEYS = frozenset({"goals.fire.target_date"})


def can_create_fact(role: str, key: str) -> bool:
    """Creating a brand-new fact row is owner-only regardless of which
    `owner` the key will end up tagged with once written (e.g.
    savings.house_deposit.balance is owner=joint on write, per Shannon's
    answer, but only the owner role may bring the key into existence at
    all) — creation is the sensitive step; writes to an existing row are
    gated by can_write_fact as normal."""
    return role == ROLE_OWNER and key in CREATABLE_FACT_KEYS


def owner_required(view):
    """Like @login_required, but also 403s any authenticated non-owner.
    Use on goal/task routes where the §1 table gives Shannon exclusive
    create/edit/delete rights (member-writable paths — task toggling,
    member's own tasks, her assigned binary/habit goal status — use the
    narrower helpers below instead, not this decorator)."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != ROLE_OWNER:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def can_create_task(role: str, user_id: int, assignee_user_id: int | None) -> bool:
    """Owner may create any task. A member may only create a task assigned
    to herself (Shannon's answer: she cannot create tasks for him or
    unassigned tasks)."""
    if role == ROLE_OWNER:
        return True
    if role != ROLE_MEMBER:
        return False
    return assignee_user_id == user_id


def can_edit_or_delete_task(
    role: str, user_id: int, creator_user_id: int, assignee_user_id: int | None
) -> bool:
    """Owner may edit/delete any task. A member may only edit/delete a task
    that is BOTH created by her AND still assigned to her — "her own", not
    merely one she happens to be assigned to (that's a toggle right, see
    can_toggle_task) or merely one she created (reassigning away a task she
    made doesn't let her keep editing it)."""
    if role == ROLE_OWNER:
        return True
    if role != ROLE_MEMBER:
        return False
    return creator_user_id == user_id and assignee_user_id == user_id


def can_toggle_task(role: str, user_id: int, assignee_user_id: int | None) -> bool:
    """Ticking a task done/undone: owner may toggle any task; a member may
    only toggle a task actually assigned to her — not unassigned, not
    someone else's, regardless of who created it."""
    if role == ROLE_OWNER:
        return True
    if role != ROLE_MEMBER:
        return False
    return assignee_user_id == user_id


def can_toggle_goal_status(
    role: str, user_id: int, goal_type: str, assignee_user_ids
) -> bool:
    """Marking a goal done/not-done (status only — no other field): owner
    may toggle any goal. A member may only toggle a goal that is BOTH
    binary or habit type AND assigned to her — a `target`-type goal is
    never status-toggleable by a member, even if she's assigned to it;
    changing it is a goal edit, which is owner-only."""
    if role == ROLE_OWNER:
        return True
    if role != ROLE_MEMBER:
        return False
    if goal_type not in ("binary", "habit"):
        return False
    return user_id in assignee_user_ids
