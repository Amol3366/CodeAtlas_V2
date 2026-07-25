from payments.service import PaymentService

def test_capture_uses_idempotency_store() -> None:
    service = PaymentService(FakeStore())
    assert service.capture("order-1") == "captured:order-1"

class FakeStore:
    def claim(self, key: str) -> str:
        return key
