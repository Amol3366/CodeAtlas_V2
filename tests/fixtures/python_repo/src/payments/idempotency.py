"""In-memory idempotency store.

The MVP uses a process-local dict; production would back this with a database.
"""

from __future__ import annotations


class IdempotencyStore:
    """Tracks idempotency keys and their previously computed results."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._results: dict[str, str] = {}

    def claim(self, idempotency_key: str) -> bool:
        """Claim a key. Returns True if newly claimed, False if already present."""
        if idempotency_key in self._claimed:
            return False
        self._claimed.add(idempotency_key)
        return True

    def record_result(self, idempotency_key: str, result: str) -> None:
        """Store the result associated with a claimed key."""
        self._results[idempotency_key] = result

    def previous_result(self, idempotency_key: str) -> str:
        """Return the result recorded for an already-claimed key."""
        return self._results[idempotency_key]
