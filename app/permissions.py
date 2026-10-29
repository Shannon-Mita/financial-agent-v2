"""
Server-side permission rules (spec §1, plus Shannon's Stage 0 amendments).

Base rule: the owner role can write anything. The member role can write a
fact only if it's owned by `partner` or `joint` — UNLESS the key is in the
protected list, in which case it's owner-only even if the fact itself is
marked `joint` (the FIRE target and plan settings are never the partner's
to edit, regardless of whose numbers feed into them).
"""

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"

VALID_FACT_OWNERS = ("shannon", "partner", "joint")

# Exact keys or dotted-prefixes that only the owner role may write, no matter
# which `owner` the fact itself is tagged with. Extend this list, don't bypass
# it, as goal/plan keys are added in Stage 1.
PROTECTED_KEY_PREFIXES = (
    "fire.target",
    "plan.",
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
