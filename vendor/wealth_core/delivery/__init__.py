"""Delivery layer: render recaps and send via Telegram (or a fake sender)."""
from .sender import (
    render_recap_telegram, deliver_recap,
    Sender, FakeSender, TelegramSender, SendResult,
)

__all__ = [
    "render_recap_telegram", "deliver_recap",
    "Sender", "FakeSender", "TelegramSender", "SendResult",
]
