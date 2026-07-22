"""Tests for PaymentService.capture."""

from __future__ import annotations

import pytest

from src.payments.gateway import FakePaymentGateway
from src.payments.idempotency import IdempotencyStore
from src.services.payment_service import PaymentError, PaymentService


def _service() -> PaymentService:
    return PaymentService(FakePaymentGateway(), IdempotencyStore())


def test_capture_returns_transaction_id() -> None:
    service = _service()
    txn = service.capture("pay_1", 500, "key-1")
    assert txn.startswith("txn_")


def test_capture_is_idempotent() -> None:
    service = _service()
    first = service.capture("pay_1", 500, "key-1")
    second = service.capture("pay_1", 500, "key-1")
    assert first == second


def test_capture_rejects_non_positive_amount() -> None:
    service = _service()
    with pytest.raises(PaymentError):
        service.capture("pay_1", 0, "key-2")
