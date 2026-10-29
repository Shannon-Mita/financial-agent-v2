"""
Tests for the delivery layer. No network: the Telegram sender's HTTP call is
injected with a fake, so we test the real send logic offline.
"""
from datetime import date, timedelta

from facts_layer import FactStore, Fact, Unit, Source
from recap import build_recap, Recap, RecapItem
from delivery import (
    render_recap_telegram, deliver_recap, FakeSender, TelegramSender,
)


def _fresh_store(partner=110000):
    s = FactStore()
    a = date.today() - timedelta(days=5)
    for key, val, unit, cat in [
        ("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, "income"),
        ("income.partner.paye_salary", partner, Unit.GBP_PER_YEAR, "income"),
        ("property.main.value", 495000, Unit.GBP, "valuation"),
        ("property.main.mortgage_balance", 375000, Unit.GBP, "mortgage"),
        ("cashflow.emergency_savings", 13000, Unit.GBP, "balance"),
        ("cashflow.monthly_essentials", 3000, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_lifestyle", 1000, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_childcare", 0, Unit.GBP_PER_MONTH, "spending"),
        ("cashflow.monthly_other", 300, Unit.GBP_PER_MONTH, "spending"),
    ]:
        s.set(Fact.create(key, val, unit, Source.USER_STATED, cat, as_of=a))
    return s


def test_render_blocked_recap():
    r = Recap(as_of=date(2026, 6, 1), blocked=True,
              block_reason="stale: mortgage (200d old)", net_worth=0,
              fire_progress_pct=0)
    out = render_recap_telegram(r)
    assert "paused" in out
    assert "mortgage" in out

def test_render_healthy_recap_has_headline():
    r = build_recap(_fresh_store(), num_children=1)
    out = render_recap_telegram(r)
    assert "<b>Wealth recap" in out
    assert "Net worth" in out
    assert "FIRE progress" in out

def test_render_includes_item_with_impact_tag():
    r = build_recap(_fresh_store(partner=110000), num_children=1)
    out = render_recap_telegram(r)
    # Should show the 60% trap or CB clawback with a £ tag
    assert "/yr" in out

def test_high_stakes_item_gets_warning():
    r = Recap(
        as_of=date(2026, 6, 1), blocked=False, block_reason="",
        net_worth=200000, fire_progress_pct=5,
        items=(RecapItem(
            title="CGT on second property", category="tax",
            impact_gbp=0, deadline=None, days_left=None,
            detail="A disposal may trigger CGT.", high_stakes=True,
        ),),
    )
    out = render_recap_telegram(r)
    assert "High-stakes" in out
    assert "adviser" in out

def test_html_is_escaped():
    r = Recap(
        as_of=date(2026, 6, 1), blocked=False, block_reason="",
        net_worth=100, fire_progress_pct=1,
        items=(RecapItem(
            title="Test <script>", category="x", impact_gbp=300,
            deadline=None, days_left=None, detail="a & b < c",
        ),),
    )
    out = render_recap_telegram(r)
    assert "<script>" not in out           # escaped
    assert "&lt;script&gt;" in out
    assert "a &amp; b" in out


# ─────────────────────────────────────────────────────────────────────────────
# Senders
# ─────────────────────────────────────────────────────────────────────────────

def test_fake_sender_records():
    sender = FakeSender()
    r = build_recap(_fresh_store(), num_children=1)
    result = deliver_recap(r, sender)
    assert result.ok
    assert len(sender.sent) == 1
    assert "Wealth recap" in sender.sent[0]

def test_telegram_sender_success_with_injected_post():
    class FakeResp:
        def json(self):
            return {"ok": True, "result": {}}
    calls = []
    def fake_post(url, payload):
        calls.append((url, payload))
        return FakeResp()

    sender = TelegramSender(bot_token="T", chat_id="123", post=fake_post)
    result = sender.send("hello")
    assert result.ok is True
    assert "api.telegram.org/botT/sendMessage" in calls[0][0]
    assert calls[0][1]["chat_id"] == "123"
    assert calls[0][1]["parse_mode"] == "HTML"

def test_telegram_sender_reports_failure():
    class FakeResp:
        def json(self):
            return {"ok": False, "description": "bad token"}
    sender = TelegramSender(bot_token="T", chat_id="123",
                            post=lambda u, p: FakeResp())
    result = sender.send("hi")
    assert result.ok is False
    assert "bad token" in result.detail

def test_telegram_sender_handles_exception():
    def boom(url, payload):
        raise ConnectionError("network down")
    sender = TelegramSender(bot_token="T", chat_id="123", post=boom)
    result = sender.send("hi")
    assert result.ok is False
    assert "network down" in result.detail
