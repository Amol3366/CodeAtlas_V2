class IdempotencyStore:
    def __init__(self) -> None:
        self._keys: set[str] = set()

    def claim(self, idempotency_key: str) -> str:
        if idempotency_key in self._keys:
            return "duplicate"
        self._keys.add(idempotency_key)
        return idempotency_key
