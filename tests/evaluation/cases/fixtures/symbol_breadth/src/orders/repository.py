"""Order persistence, kept deliberately small."""

from __future__ import annotations


class OrderRecord:
    """One stored order."""

    def __init__(self, order_id: str, total: int) -> None:
        self.order_id = order_id
        self.total = total


class OrderRepository:
    """Reads and writes `OrderRecord` values."""

    def __init__(self, rows: dict[str, OrderRecord]) -> None:
        self._rows = rows

    def get(self, order_id: str) -> OrderRecord | None:
        return self._rows.get(order_id)

    async def fetch_all(self) -> list[OrderRecord]:
        return list(self._rows.values())


def build_repository() -> OrderRepository:
    return OrderRepository({})
