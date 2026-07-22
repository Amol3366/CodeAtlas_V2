"""Notification backend."""

from __future__ import annotations


class NotificationService:
    """Sends notifications through a configured channel."""

    def __init__(self, channel: str) -> None:
        self.channel = channel

    def send(self, recipient: str, message: str) -> dict[str, str]:
        """Send a notification. Returns a delivery receipt."""
        return {"channel": self.channel, "recipient": recipient, "status": "queued"}
