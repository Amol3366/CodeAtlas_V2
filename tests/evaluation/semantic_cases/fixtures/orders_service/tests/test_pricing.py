"""Arithmetic the finance team asks about."""

from orders.models import Money, Order, OrderLine
from orders.pricing import apply_discount, shipping_for, subtotal, tax_for


def basket(*lines: OrderLine) -> Order:
    order = Order("ord-p", "cust-p")
    for line in lines:
        order.add_line(line)
    return order


def test_subtotal_adds_every_line() -> None:
    order = basket(
        OrderLine("SKU-1", 2, Money(1000)),
        OrderLine("SKU-2", 1, Money(500)),
    )

    assert subtotal(order).minor_units == 2500


def test_a_large_basket_ships_free() -> None:
    assert shipping_for(Money(6000)).is_zero()


def test_a_small_basket_pays_the_flat_fee() -> None:
    assert shipping_for(Money(1000)).minor_units == 499


def test_a_full_discount_leaves_nothing_to_pay() -> None:
    assert apply_discount(Money(2500), 100).is_zero()


def test_tax_is_rounded_down() -> None:
    assert tax_for(Money(1000)).minor_units == 87
