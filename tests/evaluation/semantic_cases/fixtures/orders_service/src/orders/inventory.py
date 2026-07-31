"""Keeping two customers from being sold the same unit."""

from .errors import OutOfStock


class InventoryLedger:
    """Stock on hand, and the part of it already spoken for."""

    def __init__(self) -> None:
        self._on_hand: dict[str, int] = {}
        self._reserved: dict[str, int] = {}

    def stock(self, sku: str, quantity: int) -> None:
        self._on_hand[sku] = self._on_hand.get(sku, 0) + quantity

    def available(self, sku: str) -> int:
        """What a new order could still take."""
        return self._on_hand.get(sku, 0) - self._reserved.get(sku, 0)

    def reserve(self, sku: str, quantity: int) -> None:
        """Hold units for an order that has not shipped yet.

        Raises OutOfStock rather than letting the count go negative, because a
        negative reservation is a promise the warehouse cannot keep.
        """
        if self.available(sku) < quantity:
            raise OutOfStock(f"{sku} short by {quantity - self.available(sku)}")
        self._reserved[sku] = self._reserved.get(sku, 0) + quantity

    def release(self, sku: str, quantity: int) -> None:
        """Give reserved units back after a cancellation."""
        held = self._reserved.get(sku, 0)
        self._reserved[sku] = max(0, held - quantity)

    def is_tracked(self, sku: str) -> bool:
        return sku in self._on_hand
