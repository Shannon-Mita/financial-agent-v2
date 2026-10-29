"""
Pure unit tests for app/fact_labels.py — no Flask, no DB needed.
"""
from app.fact_labels import (
    CATEGORY_GROUPS,
    DEFAULT_GROUP,
    FACT_LABELS,
    GROUP_ORDER,
    group_for,
    label_for,
)
from app.vendor_path import ensure_on_path

ensure_on_path()


def test_label_for_known_key_returns_friendly_name():
    assert label_for("goals.fire.target_date") == "FIRE target date"
    assert label_for("income.shannon.paye_salary") == "Shannon's PAYE salary"


def test_label_for_unknown_key_falls_back_to_raw_key():
    assert label_for("legacy.meta.taxYear") == "legacy.meta.taxYear"
    assert label_for("some.made.up.key") == "some.made.up.key"


def test_group_for_known_categories():
    assert group_for("income") == "Income"
    assert group_for("spending") == "Spending"
    assert group_for("balance") == "Savings and investments"
    assert group_for("pension") == "Pensions"
    assert group_for("mortgage") == "Property"
    assert group_for("valuation") == "Property"
    assert group_for("goal") == "Goals"


def test_group_for_unknown_category_falls_back_to_other():
    assert group_for("profile") == DEFAULT_GROUP
    assert group_for("something-new") == DEFAULT_GROUP


def test_group_order_contains_every_mapped_group_plus_other():
    assert set(GROUP_ORDER) == set(CATEGORY_GROUPS.values()) | {DEFAULT_GROUP}


def test_stage1_creatable_keys_have_labels():
    assert "goals.fire.target_date" in FACT_LABELS
    assert "savings.house_deposit.balance" in FACT_LABELS


def test_every_curated_migration_key_has_a_friendly_label():
    """Ties the label map to the actual v1 migration output, not just a
    hand-maintained key list — if from_v1.py's curated mapping ever adds a
    key, this fails until a label is added for it here."""
    from migrate import migrate_v1_profile
    from migrate.tests.test_from_v1 import AS_OF, synthetic_blob

    facts, _report = migrate_v1_profile(synthetic_blob(), AS_OF)
    curated_keys = [f.key for f in facts if not f.key.startswith("legacy.")]

    assert len(curated_keys) == 47  # Stage 0's curated fact count
    for key in curated_keys:
        assert key in FACT_LABELS, f"{key} is produced by the migration but has no label"


def test_every_curated_migration_key_groups_somewhere_sensible():
    """Every curated key's category must map to one of the real groups, or
    deliberately to Other (profile facts) — never silently miscategorised."""
    from migrate import migrate_v1_profile
    from migrate.tests.test_from_v1 import AS_OF, synthetic_blob

    facts, _report = migrate_v1_profile(synthetic_blob(), AS_OF)
    curated = [f for f in facts if not f.key.startswith("legacy.")]

    for fact in curated:
        assert group_for(fact.category) in GROUP_ORDER
