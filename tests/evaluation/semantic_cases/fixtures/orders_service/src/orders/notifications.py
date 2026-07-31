"""Telling the customer what happened to their order."""

from .models import Order


class Notifier:
    """Collects messages instead of sending them, so tests stay offline."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_confirmation(self, order: Order) -> None:
        """Acknowledge an order the customer has just placed."""
        self.sent.append(f"confirmed:{order.reference}")

    def send_cancellation(self, order: Order) -> None:
        """Let the customer know the order will not be shipped."""
        self.sent.append(f"cancelled:{order.reference}")

    def send_delay_notice(self, order: Order, days: int) -> None:
        """Warn that delivery will take longer than promised."""
        self.sent.append(f"delayed:{order.reference}:{days}")

    def message_count(self) -> int:
        return len(self.sent)

    def clear(self) -> None:
        self.sent = []
