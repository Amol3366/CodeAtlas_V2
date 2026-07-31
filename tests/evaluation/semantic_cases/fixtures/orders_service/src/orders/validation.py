"""Rejecting a basket before it becomes an order."""

from .errors import LineItemInvalid
from .models import Order, OrderLine

MAX_QUANTITY_PER_LINE = 99
SKU_PREFIX = "SKU-"


def check_line(line: OrderLine) -> None:
    """Reject a line the warehouse could never pick."""
    if line.quantity <= 0:
        raise LineItemInvalid("quantity must be positive")
    if line.quantity > MAX_QUANTITY_PER_LINE:
        raise LineItemInvalid(f"quantity above {MAX_QUANTITY_PER_LINE}")
    if not line.sku.startswith(SKU_PREFIX):
        raise LineItemInvalid("sku is not recognisable")
    if line.unit_price.minor_units < 0:
        raise LineItemInvalid("price cannot be negative")


def check_order(order: Order) -> None:
    """Reject a basket that is not ready to be placed."""
    if order.is_empty():
        raise LineItemInvalid("an order needs at least one line")
    for line in order.lines:
        check_line(line)


def is_duplicate_sku(order: Order) -> bool:
    """Whether the same product was added on two separate lines."""
    seen = [line.sku for line in order.lines]
    return len(seen) != len(set(seen))
