"""Partner-facing payment routes (FastAPI)."""

from __future__ import annotations

from fastapi import APIRouter

from src.config.settings import get_settings
from src.payments.gateway import FakePaymentGateway
from src.payments.idempotency import IdempotencyStore
from src.services.payment_service import PaymentService

router = APIRouter(prefix="/partner/payments", tags=["payments"])

_service = PaymentService(FakePaymentGateway(), IdempotencyStore())


@router.post("/capture")
def capture_partner_payment(payment_id: str, amount: int, idempotency_key: str) -> dict[str, str]:
    """Capture a partner payment.

    The partner payment endpoint calls PaymentService.capture.
    """
    settings = get_settings()
    if amount > settings.max_capture_amount:
        return {"status": "rejected", "reason": "amount exceeds limit"}
    transaction_id = _service.capture(payment_id, amount, idempotency_key)
    return {"status": "captured", "transaction_id": transaction_id}
