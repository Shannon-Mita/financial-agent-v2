"""
Pure unit tests for the two placeholder-load bugs Shannon flagged:

  1. infer_owner() used to read only the key's *second* dotted segment, so
     any "legacy."-prefixed key (where the real owner segment is third, not
     second) always fell through to "joint".
  2. There was no way to exclude the uncurated "legacy.*" passthrough from a
     load — this is now the --exclude-prefix default for Stage 0.

No DB, no sqlite fixture needed — these are plain functions.
"""
from scripts.load_placeholder_facts import (
    DEFAULT_EXCLUDE_PREFIXES,
    infer_owner,
    is_excluded,
    resolve_exclude_prefixes,
)


# ── infer_owner ──────────────────────────────────────────────────────────

def test_infer_owner_second_segment_unchanged():
    assert infer_owner("income.shannon.paye_salary") == "shannon"
    assert infer_owner("income.partner.paye_salary") == "partner"


def test_infer_owner_no_owner_segment_is_joint():
    assert infer_owner("property.main.value") == "joint"
    assert infer_owner("children.0.dob") == "joint"


def test_infer_owner_legacy_prefixed_key_finds_owner_in_third_segment():
    # The actual bug: "legacy." pushes shannon/partner to the third segment,
    # and the old code only ever looked at the second.
    assert infer_owner("legacy.income.shannon.bonusTiming") == "shannon"
    assert infer_owner("legacy.investments.partner.cryptoPlatform") == "partner"


def test_infer_owner_legacy_key_with_no_owner_segment_is_still_joint():
    assert infer_owner("legacy.goals.notes") == "joint"


def test_infer_owner_matches_leftmost_segment_first():
    # Contrived, but pins down the "first match wins" rule explicitly.
    assert infer_owner("shannon.partner.transfer") == "shannon"


# ── resolve_exclude_prefixes / is_excluded ──────────────────────────────

def test_default_excludes_legacy_only():
    assert resolve_exclude_prefixes(None) == DEFAULT_EXCLUDE_PREFIXES
    assert DEFAULT_EXCLUDE_PREFIXES == ("legacy.",)


def test_explicit_exclude_prefix_replaces_default_not_appends():
    # argparse action="append" with a non-None default would ADD to it;
    # resolve_exclude_prefixes must instead treat any explicit use of the
    # flag as a full replacement of the "legacy." default.
    assert resolve_exclude_prefixes(["iht."]) == ("iht.",)


def test_empty_string_prefix_means_exclude_nothing():
    assert resolve_exclude_prefixes([""]) == ()


def test_multiple_exclude_prefixes_supported():
    assert resolve_exclude_prefixes(["legacy.", "iht."]) == ("legacy.", "iht.")


def test_is_excluded_matches_prefix():
    prefixes = resolve_exclude_prefixes(None)
    assert is_excluded("legacy.income.shannon.benefitsInKind", prefixes)
    assert not is_excluded("income.shannon.paye_salary", prefixes)


def test_is_excluded_with_no_prefixes_excludes_nothing():
    assert not is_excluded("legacy.anything", ())
