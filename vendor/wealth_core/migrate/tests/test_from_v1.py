"""
Tests for the v1 -> facts migration. Uses a SYNTHETIC blob shaped like the real
household profile (same structure, same known quirks — empty-string fields,
mismatched goals) but with placeholder numbers, so no real financial data lives
in test code.
"""
from datetime import date

from facts_layer import FactStore
from migrate import migrate_v1_profile


def synthetic_blob():
    """Shaped like the real v1 profile, deliberately reproducing its two known
    quirks: an empty-string numeric field, and mismatched FIRE targets."""
    return {
        "people": {
            "shannon": {"dob": "1988-04-07"},
            "partner": {"dob": "1990-01-05"},
        },
        "children": [
            {"dob": "2025-10-06", "childBenefitClaiming": False},
        ],
        "income": {
            "shannon": {
                "payeSalary": 40000,
                "selfEmployedProfit": 0,
                "dividends": "",          # the quirk: empty string, not 0
                "savingsInterest": 0,
                "bonusExpected": 0,
                "giftAidDonations": 0,
            },
            "partner": {
                "payeSalary": 90000,
                "maternityPayThisYear": 0,
                "dividends": 0,
                "savingsInterest": 0,
                "bonusExpected": 0,
                "giftAidDonations": 0,
            },
        },
        "property": {
            "currentEstimatedValue": 400000,
            "mortgageOutstanding": 300000.55,
            "mortgageRate": 4.5,
            "mortgageFixedRateEndDate": "2027-01-01",
        },
        "pensions": {
            "shannon": {"hasPension": False, "currentValue": 0,
                       "monthlyEmployee": 0, "monthlyEmployer": 0},
            "partner": {"hasPension": True, "currentValue": 5000,
                       "monthlyEmployee": 150, "monthlyEmployer": 100,
                       "expressionOfWishesUpdated": False},
        },
        "isa": {
            "shannon": {"stocksShares": {"value": 10000}, "cash": {"value": 0}},
            "partner": {"stocksShares": {"value": 5000}, "cash": {"value": 2000}},
            "junior": {"value": 1000},
        },
        "investments": {
            "shannon": {"cryptoValue": 20000},
            "partner": {"stocksGIAValue": 3000},
        },
        "cashflow": {
            "emergencyCashSavings": 10000,
            "monthlyEssentials": 3000,
            "monthlyLifestyle": 1000,
            "monthlyChildcare": 0,
            "monthlyOther": 500,
        },
        "goals": {
            "fire": {
                "targetMonthlyIncome": 8000,   # implies 8000*12/0.04 = 2,400,000
                "targetAge": 45,
                "safeWithdrawalRate": 4.0,
            },
            "netWorth": {"targetAmount": 3000000},  # deliberately mismatched
        },
    }


AS_OF = date(2026, 6, 1)


def test_curated_numeric_fields_map_correctly():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    by_key = {f.key: f for f in facts}
    assert by_key["income.shannon.paye_salary"].value == 40000
    assert by_key["income.partner.paye_salary"].value == 90000
    assert by_key["property.main.value"].value == 400000
    assert by_key["property.main.mortgage_balance"].value == 300000.55

def test_empty_string_coerced_to_zero():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    by_key = {f.key: f for f in facts}
    assert by_key["income.shannon.dividends"].value == 0.0
    assert isinstance(by_key["income.shannon.dividends"].value, float)
    assert "income.shannon.dividends" in report.coerced_fields

def test_bool_fields_map_correctly():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    by_key = {f.key: f for f in facts}
    assert by_key["pensions.shannon.has_pension"].value is False
    assert by_key["pensions.partner.has_pension"].value is True

def test_date_fields_map_correctly():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    by_key = {f.key: f for f in facts}
    assert by_key["property.main.fixed_rate_end"].value == "2027-01-01"
    assert by_key["people.shannon.dob"].value == "1988-04-07"

def test_fire_target_years_derived():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    by_key = {f.key: f for f in facts}
    # partner born 1990-01-05, as_of 2026-06-01 -> age 36; target age 45 -> 9 years
    assert by_key["goals.fire.target_years"].value == 9
    assert by_key["goals.fire.target_years"].source.value == "derived"

def test_fire_target_number_derived_from_formula():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    by_key = {f.key: f for f in facts}
    # 8000 * 12 / 0.04 = 2,400,000
    assert by_key["goals.fire.target_number"].value == 2400000

def test_discrepancy_detected_for_mismatched_goals():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    assert len(report.discrepancies) == 1
    d = report.discrepancies[0]
    assert "FIRE target mismatch" in d.description
    assert "2,400,000" in d.detail
    assert "3,000,000" in d.detail

def test_no_discrepancy_when_goals_agree():
    blob = synthetic_blob()
    blob["goals"]["netWorth"]["targetAmount"] = 2400000  # now matches
    facts, report = migrate_v1_profile(blob, AS_OF)
    assert report.discrepancies == ()

def test_legacy_passthrough_captures_uncurated_fields():
    blob = synthetic_blob()
    blob["protection"] = {"shannon": {"willInPlace": True}}
    facts, report = migrate_v1_profile(blob, AS_OF)
    legacy_keys = [f.key for f in facts if f.key.startswith("legacy.")]
    assert any("protection.shannon.willInPlace" in k for k in legacy_keys)
    assert report.legacy_count > 0

def test_all_facts_carry_the_single_as_of():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    assert all(f.as_of == AS_OF for f in facts)

def test_migrated_facts_load_into_store_and_feed_recap():
    """End-to-end: migrated facts are usable by the real recap builder."""
    facts, report = migrate_v1_profile(synthetic_blob(), date.today())
    store = FactStore()
    store.set_many(facts)

    from recap import build_recap
    recap = build_recap(store, num_children=1)
    assert recap.blocked is False
    assert recap.net_worth > 0

def test_report_summary_is_readable():
    facts, report = migrate_v1_profile(synthetic_blob(), AS_OF)
    text = report.summary()
    assert "Migrated" in text
    assert "Discrepancies found" in text
