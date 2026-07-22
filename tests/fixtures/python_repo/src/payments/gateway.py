"""Payment gateway abstraction and a fake local implementation."""

from __future__ import annotations

import uuid
from typing import Protocol


class PaymentGateway(Protocol):
    """A payment processor capable of charging and refunding."""

    def charge(self, payment_id: str, amount: int) -> str:
        ...

    def refund(self, transaction_id: str, amount: int) -> str:
        ...


class FakePaymentGateway:
    """Deterministic-enough fake gateway for local development and tests."""

    def charge(self, payment_id: str, amount: int) -> str:
        return f"txn_{uuid.uuid5(uuid.NAMESPACE_URL, payment_id).hex[:12]}"

    def refund(self, transaction_id: str, amount: int) -> str:
        return f"rfnd_{transaction_id}"
