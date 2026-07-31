"""Turning a basket into an amount to charge."""

from .models import Money, Order

TAX_RATE_BASIS_POINTS = 875
FREE_SHIPPING_THRESHOLD = Money(5000)
FLAT_SHIPPING_FEE = Money(499)


def subtotal(order: Order) -> Money:
    """Add up every line before tax, discounts, or delivery."""
    running = Money(0)
    for line in order.lines:
        running = running.plus(line.line_total())
    return running


def tax_for(amount: Money) -> Money:
    """Sales tax on an amount, rounded down to the nearest cent."""
    return Money(amount.minor_units * TAX_RATE_BASIS_POINTS // 10000)


def shipping_for(amount: Money, express: bool) -> Money:
    """Delivery is free once the basket is large enough to absorb it."""
    if express or amount.minor_units < FREE_SHIPPING_THRESHOLD.minor_units:
        return FLAT_SHIPPING_FEE
    return Money(0)


def apply_discount(amount: Money, percent_off: int) -> Money:
    """Reduce an amount by a whole percentage, never below zero."""
    if percent_off <= 0:
        return amount
    if percent_off >= 100:
        return Money(0)
    return Money(amount.minor_units * (100 - percent_off) // 100)


def total_for(order: Order, percent_off: int = 0) -> Money:
    """The final amount: lines, less discount, plus tax and delivery."""
    goods = apply_discount(subtotal(order), percent_off)
    return goods.plus(tax_for(goods)).plus(shipping_for(goods))
