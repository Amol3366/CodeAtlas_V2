"""The nouns of the ordering domain."""

from enum import Enum


class OrderStatus(Enum):
    """Where an order sits in its lifecycle."""

    DRAFT = "draft"
    PLACED = "placed"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Money:
    """An amount in minor units, so arithmetic never loses fractions."""

    def __init__(self, minor_units: int, currency: str = "USD") -> None:
        self.minor_units = minor_units
        self.currency = currency

    def plus(self, other: "Money") -> "Money":
        return Money(self.minor_units + other.minor_units, self.currency)

    def times(self, factor: int) -> "Money":
        return Money(self.minor_units * factor, self.currency)

    def is_zero(self) -> bool:
        return self.minor_units == 0

    def as_decimal_string(self) -> str:
        return f"{self.minor_units // 100}.{self.minor_units % 100:02d}"


class OrderLine:
    """One product and how many of it the customer wants."""

    def __init__(self, sku: str, quantity: int, unit_price: Money) -> None:
        self.sku = sku
        self.quantity = quantity
        self.unit_price = unit_price

    def line_total(self) -> Money:
        return self.unit_price.times(self.quantity)

    def describe(self) -> str:
        return f"{self.quantity} x {self.sku}"


class Order:
    """A customer's basket once it has a reference of its own."""

    def __init__(self, reference: str, customer_id: str) -> None:
        self.reference = reference
        self.customer_id = customer_id
        self.lines: list[OrderLine] = []
        self.status = OrderStatus.DRAFT

    def add_line(self, line: OrderLine) -> None:
        self.lines.append(line)

    def line_count(self) -> int:
        return len(self.lines)

    def is_empty(self) -> bool:
        return not self.lines

    def mark_placed(self) -> None:
        self.status = OrderStatus.PLACED

    def mark_cancelled(self) -> None:
        self.status = OrderStatus.CANCELLED

    def is_cancelled(self) -> bool:
        return self.status is OrderStatus.CANCELLED
