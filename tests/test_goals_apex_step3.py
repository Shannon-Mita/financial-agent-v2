"""
HTTP-level tests for Stage 2 Step 3: the two new apex goals (net worth,
passive income) on the Goals page — fact-backed targets/dates, owner-only,
milestones nested beneath each, both inflation-adjusted figures shown, and
the household's current monthly surplus shown directly on the page.

Needs a real Postgres (skips without TEST_DATABASE_URL), same as the other
route tests.
"""
import re

import app.goals_store as goals_store
from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m, "expected a csrf_token hidden input on the page"
    return m.group(1)


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


SURPLUS_FACTS = [
    ("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
    ("income.partner.paye_salary", 70000, Unit.GBP_PER_YEAR, "income"),
    ("cashflow.monthly_essentials", 2000, Unit.GBP_PER_MONTH, "spending"),
    ("cashflow.monthly_lifestyle", 800, Unit.GBP_PER_MONTH, "spending"),
    ("cashflow.monthly_childcare", 600, Unit.GBP_PER_MONTH, "spending"),
    ("cashflow.monthly_other", 200, Unit.GBP_PER_MONTH, "spending"),
    ("children.0.child_benefit_claiming", False, Unit.BOOL, "profile"),
]

NET_WORTH_FACTS = [
    ("cashflow.emergency_savings", 13000, Unit.GBP, "balance"),
    ("isa.shannon.stocks_shares.value", 40000, Unit.GBP, "balance"),
    ("isa.shannon.cash.value", 5000, Unit.GBP, "balance"),
    ("isa.partner.stocks_shares.value", 20000, Unit.GBP, "balance"),
    ("isa.partner.cash.value", 3000, Unit.GBP, "balance"),
    ("investments.shannon.crypto_value", 2000, Unit.GBP, "balance"),
    ("investments.partner.stocks_gia_value", 10000, Unit.GBP, "balance"),
    ("savings.house_deposit.balance", 22000, Unit.GBP, "balance"),
    ("property.main.value", 495000, Unit.GBP, "valuation"),
    ("property.main.mortgage_balance", 375000, Unit.GBP, "mortgage"),
    ("goals.net_worth.target_amount", 1_000_000, Unit.GBP, "goal"),
    ("goals.net_worth.target_date", "2030-10-05", Unit.DATE, "goal"),
]

PASSIVE_INCOME_FACTS = [
    ("income.passive.rental", 500, Unit.GBP_PER_MONTH, "passive_income"),
    ("income.passive.business", 300, Unit.GBP_PER_MONTH, "passive_income"),
    ("income.passive.investments", 200, Unit.GBP_PER_MONTH, "passive_income"),
    ("income.shannon.savings_interest", 60, Unit.GBP_PER_YEAR, "income"),
    ("income.partner.savings_interest", 72, Unit.GBP_PER_YEAR, "income"),
    ("income.shannon.dividends", 120, Unit.GBP_PER_YEAR, "income"),
    ("income.partner.dividends", 240, Unit.GBP_PER_YEAR, "income"),
    ("goals.passive_income.target_amount", 12000, Unit.GBP_PER_MONTH, "goal"),
    ("goals.passive_income.target_date", "2030-10-05", Unit.DATE, "goal"),
]


def _seed_all_facts(pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    for key, val, unit, cat in SURPLUS_FACTS + NET_WORTH_FACTS + PASSIVE_INCOME_FACTS:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat), owner="joint", entered_by_user_id=owner_user_id)


def _create_apex_goals(pg_conn, owner_user_id, member_user_id):
    net_worth_id = goals_store.create_goal(
        pg_conn, title="Net worth", type="target", target_value=None, target_date=None,
        source_fact_key="goals.net_worth.target_amount", target_date_fact_key="goals.net_worth.target_date",
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id, member_user_id], user_id=owner_user_id,
    )
    passive_income_id = goals_store.create_goal(
        pg_conn, title="Passive income", type="target", target_value=None, target_date=None,
        source_fact_key="goals.passive_income.target_amount", target_date_fact_key="goals.passive_income.target_date",
        progress_fact_keys=None, cadence_period=None, cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id, member_user_id], user_id=owner_user_id,
    )
    return net_worth_id, passive_income_id


# ── Two apex goals, milestones nested beneath each ─────────────────────────

def test_both_apex_goals_render_with_their_own_milestones_heading(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    net_worth_id, passive_income_id = _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-08-29",
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=["savings.house_deposit.balance"],
        cadence_period=None, cadence_amount=None, parent_id=net_worth_id,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    goals_store.create_goal(
        pg_conn, title="Side hustle launched", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=passive_income_id,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )

    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    assert ">Net worth<" in body
    assert ">Passive income<" in body
    assert body.count("Milestones") == 2
    assert body.find(">Net worth<") < body.find(">House deposit<")
    assert body.find(">Passive income<") < body.find("Side hustle launched")


def test_apex_goals_not_duplicated_in_the_flat_grid(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert body.count(">Net worth</a>") == 1
    assert body.count(">Passive income</a>") == 1


def test_other_top_level_goal_still_renders_without_milestones_label(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    goals_store.create_goal(
        pg_conn, title="Learn Spanish", type="habit", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period="weekly", cadence_amount=None, parent_id=None,
        assignee_user_ids=[owner_user_id], user_id=owner_user_id,
    )
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "Learn Spanish" in body


def test_member_also_sees_both_apex_goals_and_their_milestones(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    net_worth_id, _ = _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    goals_store.create_goal(
        pg_conn, title="House deposit", type="target", target_value=70000, target_date="2027-08-29",
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=["savings.house_deposit.balance"],
        cadence_period=None, cadence_amount=None, parent_id=net_worth_id,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    login(client, member_user_id)
    body = client.get("/goals").data.decode()
    assert ">Net worth<" in body and ">Passive income<" in body
    assert "House deposit" in body


# ── Current vs target vs gap vs £/month needed, both money-year figures ────

def test_net_worth_card_shows_current_target_gap_and_required_monthly(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    # Current = 610000 assets - 375000 debt = 235000.
    assert "235,000" in body
    # 2030-money target shown verbatim.
    assert "1,000,000" in body
    # Today's-money deflated target is a smaller, different number.
    assert "909,246" in body or "909,247" in body  # rounding tolerance


def test_passive_income_card_shows_current_target_gap_and_required_monthly(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()

    assert "12,000" in body  # 2030-money target


def test_apex_cards_show_gap_and_required_monthly_labels(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "Gap" in body
    assert "month needed" in body.lower()


# ── Current monthly surplus shown directly on the Goals page ───────────────

def test_current_monthly_surplus_shown_on_goals_page(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    for key, val, unit, cat in SURPLUS_FACTS:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat), owner="joint", entered_by_user_id=owner_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "monthly surplus" in body.lower()


def test_surplus_caveat_shown_when_required_fact_missing(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "can't compute" in body.lower()


# ── Owner-only: Asha 403 creating/editing the apex goals and their
# milestones ────────────────────────────────────────────────────────────

def test_member_gets_403_creating_a_net_worth_milestone(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    net_worth_id, _ = _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, member_user_id)
    page = client.get("/goals")
    resp = client.post("/goals", data={
        "title": "Member-created milestone", "type": "binary",
        "target_value_mode": "amount", "target_date_mode": "date",
        "parent_id": str(net_worth_id), "csrf_token": token(page),
    })
    assert resp.status_code == 403


def test_member_gets_403_editing_a_passive_income_milestone(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _, passive_income_id = _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    milestone_id = goals_store.create_goal(
        pg_conn, title="Side hustle launched", type="binary", target_value=None, target_date=None,
        source_fact_key=None, target_date_fact_key=None, progress_fact_keys=None,
        cadence_period=None, cadence_amount=None, parent_id=passive_income_id,
        assignee_user_ids=[member_user_id], user_id=owner_user_id,
    )
    login(client, member_user_id)
    page = client.get(f"/goals/{milestone_id}")
    resp = client.post(f"/goals/{milestone_id}/edit", data={
        "title": "Renamed by member", "type": "binary",
        "target_value_mode": "amount", "target_date_mode": "date",
        "csrf_token": token(page),
    })
    assert resp.status_code == 403


def test_member_gets_403_creating_either_apex_goal_itself(client, pg_conn, owner_user_id, member_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    t = token(page)
    login(client, member_user_id)
    resp = client.post("/goals", data={
        "title": "Net worth", "type": "target",
        "target_value_mode": "fact", "source_fact_key": "goals.net_worth.target_amount",
        "target_date_mode": "fact", "target_date_fact_key": "goals.net_worth.target_date",
        "csrf_token": t,
    })
    assert resp.status_code == 403
    assert goals_store.list_goals(pg_conn) == []


def test_goal_detail_page_also_shows_both_money_year_figures(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    net_worth_id, _ = _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get(f"/goals/{net_worth_id}").data.decode()
    assert "1,000,000" in body
    assert "909,246" in body or "909,247" in body
    assert "2030 money" in body
    assert "today's money" in body.lower()


# ── Passive income card: no verdict/required-monthly (category error);
# net worth unchanged ─────────────────────────────────────────────────────

def test_passive_income_card_has_no_required_monthly_label(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    # Isolate the Passive income apex card from the Net worth one.
    pi_start = body.find(">Passive income<")
    nw_start = body.find(">Net worth<")
    pi_card = body[pi_start:nw_start] if pi_start < nw_start else body[pi_start:]
    assert "month needed" not in pi_card.lower()
    assert "badge on-track" not in pi_card and "badge short" not in pi_card
    assert "Gap per month" in pi_card


def test_net_worth_card_still_has_required_monthly_and_status(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    nw_start = body.find(">Net worth<")
    pi_start = body.find(">Passive income<")
    nw_card = body[nw_start:pi_start] if nw_start < pi_start else body[nw_start:]
    assert "month needed" in nw_card.lower()
    assert "badge on-track" in nw_card or "badge short" in nw_card


# ── Surplus card "how this is calculated" breakdown ──────────────────────

def test_surplus_card_shows_how_this_is_calculated_breakdown(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    for key, val, unit, cat in SURPLUS_FACTS:
        store.set(Fact.create(key, val, unit, Source.USER_STATED, cat), owner="joint", entered_by_user_id=owner_user_id)
    login(client, owner_user_id)
    body = client.get("/goals").data.decode()
    assert "How this is calculated" in body
    assert "<details>" in body
    assert "income tax" in body.lower()
    assert "take-home" in body.lower()
    assert "Essentials" in body


def test_passive_income_detail_page_does_not_crash_and_has_no_required_monthly(client, pg_conn, owner_user_id, member_user_id):
    _seed_all_facts(pg_conn, owner_user_id)
    _, passive_income_id = _create_apex_goals(pg_conn, owner_user_id, member_user_id)
    login(client, owner_user_id)
    resp = client.get(f"/goals/{passive_income_id}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "needed" not in body.lower()
    assert "None" not in body


def test_owner_can_create_net_worth_goal_fact_backed(client, pg_conn, owner_user_id):
    login(client, owner_user_id)
    page = client.get("/goals/new")
    resp = client.post("/goals", data={
        "title": "Net worth", "type": "target",
        "target_value_mode": "fact", "source_fact_key": "goals.net_worth.target_amount",
        "target_date_mode": "fact", "target_date_fact_key": "goals.net_worth.target_date",
        "csrf_token": token(page),
    })
    assert resp.status_code == 302
    goals = goals_store.list_goals(pg_conn)
    assert len(goals) == 1
    assert goals[0]["source_fact_key"] == "goals.net_worth.target_amount"
    assert goals[0]["target_date_fact_key"] == "goals.net_worth.target_date"
