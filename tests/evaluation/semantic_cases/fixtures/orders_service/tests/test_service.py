"""Ordering behaviour that has to keep working."""

from orders.inventory import InventoryLedger
from orders.models import Money
from orders.notifications import Notifier
from orders.repository import OrderRepository
from orders.service import OrderService


def build_service() -> OrderService:
    ledger = InventoryLedger()
    ledger.stock("SKU-1", 10)
    return OrderService(OrderRepository(), ledger, Notifier())


def test_placing_an_order_reserves_its_stock() -> None:
    service = build_service()
    service.draft("ord-1", "cust-1")
    service.add_item("ord-1", "SKU-1", 2, Money(1000))

    service.place("ord-1")

    assert service.ledger.available("SKU-1") == 8


def test_cancelling_returns_the_reserved_units() -> None:
    service = build_service()
    service.draft("ord-2", "cust-1")
    service.add_item("ord-2", "SKU-1", 3, Money(1000))
    service.place("ord-2")

    service.cancel("ord-2")

    assert service.ledger.available("SKU-1") == 10


def test_the_customer_is_told_when_an_order_is_placed() -> None:
    service = build_service()
    service.draft("ord-3", "cust-1")
    service.add_item("ord-3", "SKU-1", 1, Money(1000))

    service.place("ord-3")

    assert service.notifier.sent == ["confirmed:ord-3"]
