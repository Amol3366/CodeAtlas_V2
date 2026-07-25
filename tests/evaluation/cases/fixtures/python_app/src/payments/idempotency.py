class IdempotencyStore:
    def __init__(self) -> None:
        self._keys: set[str] = set()

    def claim(self, key: str) -> str:
        if key in self._keys:
            return "duplicate"
        self._keys.add(key)
        return key
