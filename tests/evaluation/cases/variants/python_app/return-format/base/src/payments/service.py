from .idempotency import IdempotencyStore

class PaymentService:
    def __init__(self, store: IdempotencyStore) -> None:
        self.store = store

    def capture(self, key: str) -> str:
        if not key:
            raise ValueError("key is required")
        token = self.store.claim(key)
        return f"token={token}"
