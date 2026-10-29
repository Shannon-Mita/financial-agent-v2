"""
Delivery layer (architecture v0.3, Layer 7).

Turns a Recap (and, later, discovery output) into a message and sends it. Two
design points from the reviews:

  - DECISION-TRIGGER FORMAT, not a content digest. Each item leads with the £
    impact or the deadline and a one-line "what to do", so the reader gets a task
    not an article.
  - The sender is INJECTED. Tests pass a fake sender and never touch the network.
    A real Telegram sender is provided but only imported when actually used, so
    the core stays dependency-light and offline-testable.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable, Protocol

from recap import Recap


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

def render_recap_telegram(recap: Recap) -> str:
    """Render a Recap as Telegram-flavoured HTML (bold/italic supported)."""
    if recap.blocked:
        return (
            "<b>Wealth recap — paused</b>\n"
            "I can't produce this month's recap until you confirm some numbers.\n\n"
            f"<i>Please update:</i> {html.escape(recap.block_reason)}"
        )

    lines = [f"<b>Wealth recap — {recap.as_of.isoformat()}</b>"]
    lines.append(f"Net worth: <b>£{int(recap.net_worth):,}</b>")
    lines.append(f"FIRE progress: <b>{recap.fire_progress_pct}%</b>")

    if not recap.items:
        lines.append("\n✓ Nothing material needs action this month.")
    else:
        lines.append(f"\n<b>{len(recap.items)} thing(s) worth your attention:</b>")
        for i, it in enumerate(recap.items, 1):
            header = f"{i}. <b>{html.escape(it.title)}</b>"
            tags = []
            if it.impact_gbp:
                tags.append(f"~£{int(it.impact_gbp):,}/yr")
            if it.days_left is not None:
                tags.append(f"{it.days_left} days left")
            if tags:
                header += f" <i>({' · '.join(tags)})</i>"
            lines.append(header)
            lines.append(html.escape(it.detail))
            if it.high_stakes:
                lines.append("⚠️ <i>High-stakes — confirm with a regulated adviser before acting.</i>")

    if recap.suppressed_count:
        lines.append(f"\n<i>({recap.suppressed_count} minor item(s) below "
                     f"threshold not shown.)</i>")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Sender abstraction
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SendResult:
    ok: bool
    detail: str = ""


class Sender(Protocol):
    def send(self, message: str) -> SendResult: ...


@dataclass
class FakeSender:
    """Test/dev sender — records messages instead of sending them."""
    sent: list = None

    def __post_init__(self):
        if self.sent is None:
            self.sent = []

    def send(self, message: str) -> SendResult:
        self.sent.append(message)
        return SendResult(ok=True, detail="recorded")


@dataclass
class TelegramSender:
    """Real Telegram sender. `post` is injected so it stays testable and the
    core needs no HTTP dependency until actually used."""
    bot_token: str
    chat_id: str
    post: Callable[[str, dict], object] = None   # e.g. requests.post

    def send(self, message: str) -> SendResult:
        if self.post is None:
            import requests  # imported lazily, only in real use
            post = requests.post
        else:
            post = self.post
        try:
            resp = post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
            )
            data = resp.json() if hasattr(resp, "json") else {}
            ok = bool(data.get("ok", False))
            return SendResult(ok=ok, detail="sent" if ok else str(data))
        except Exception as e:  # noqa: BLE001
            return SendResult(ok=False, detail=str(e))


def deliver_recap(recap: Recap, sender: Sender) -> SendResult:
    """Render and send a recap through any sender."""
    return sender.send(render_recap_telegram(recap))
