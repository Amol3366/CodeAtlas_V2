"""Where orders live between requests."""

from .errors import OrderNotFound
from .models import Order


class OrderRepository:
    """An in-memory store, keyed by the order's own reference."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def save(self, order: Order) -> None:
        self._orders[order.reference] = order

    def get(self, reference: str) -> Order:
        """Fetch one order, or say plainly that it is not there."""
        if reference not in self._orders:
            raise OrderNotFound(reference)
        return self._orders[reference]

    def exists(self, reference: str) -> bool:
        return reference in self._orders

    def for_customer(self, customer_id: str) -> list[Order]:
        """Every order belonging to one customer, oldest reference first."""
        matches = [
            order
            for order in self._orders.values()
            if order.customer_id == customer_id
        ]
        return sorted(matches, key=lambda order: order.reference)

    def remove(self, reference: str) -> None:
        self._orders.pop(reference, None)

    def count(self) -> int:
        return len(self._orders)
