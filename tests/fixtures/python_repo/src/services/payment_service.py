"""Payment capture service with idempotency protection."""

from __future__ import annotations

from src.payments.gateway import PaymentGateway
from src.payments.idempotency import IdempotencyStore


class PaymentError(Exception):
    """Raised when a payment cannot be captured."""


class PaymentService:
    """Captures payments exactly once using an idempotency store."""

    def __init__(self, gateway: PaymentGateway, store: IdempotencyStore) -> None:
        self._gateway = gateway
        self._store = store

    def capture(self, payment_id: str, amount: int, idempotency_key: str) -> str:
        """Capture a payment. Idempotent on ``idempotency_key``.

        Returns the gateway transaction id. Raises PaymentError on failure.
        """
        if not self._store.claim(idempotency_key):
            return self._store.previous_result(idempotency_key)

        if amount <= 0:
            raise PaymentError("amount must be positive")

        transaction_id = self._gateway.charge(payment_id, amount)
        self._store.record_result(idempotency_key, transaction_id)
        return transaction_id

    def refund(self, transaction_id: str, amount: int) -> str:
        """Refund a previously captured payment."""
        return self._gateway.refund(transaction_id, amount)
