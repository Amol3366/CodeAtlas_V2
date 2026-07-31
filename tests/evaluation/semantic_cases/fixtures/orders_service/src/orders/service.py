"""The one place the ordering steps are sequenced."""

from .errors import AlreadyCancelled
from .inventory import InventoryLedger
from .models import Money, Order, OrderLine
from .notifications import Notifier
from .pricing import total_for
from .repository import OrderRepository
from .validation import check_order


class OrderService:
    """Places and cancels orders, in the order the steps must happen."""

    def __init__(
        self,
        repository: OrderRepository,
        ledger: InventoryLedger,
        notifier: Notifier,
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.notifier = notifier

    def draft(self, reference: str, customer_id: str) -> Order:
        """Open an empty basket and remember it."""
        order = Order(reference, customer_id)
        self.repository.save(order)
        return order

    def add_item(
        self, reference: str, sku: str, quantity: int, unit_price: Money
    ) -> Order:
        """Put a product in an existing basket."""
        order = self.repository.get(reference)
        order.add_line(OrderLine(sku, quantity, unit_price))
        self.repository.save(order)
        return order

    def place(self, reference: str, percent_off: int = 0) -> Money:
        """Validate, hold stock, charge, and confirm — in that order.

        Stock is reserved before the confirmation goes out, so a customer is
        never told an order succeeded when the warehouse could not fill it.
        """
        order = self.repository.get(reference)
        check_order(order)
        for line in order.lines:
            self.ledger.reserve(line.sku, line.quantity)
        amount = total_for(order, percent_off)
        order.mark_placed()
        self.repository.save(order)
        self.notifier.send_confirmation(order)
        return amount

    def cancel(self, reference: str) -> None:
        """Undo a placed order and return its stock to the shelf.

        Refuses a second cancellation rather than releasing the same units
        twice, which would let the ledger drift above what is on the shelf.
        """
        order = self.repository.get(reference)
        if order.is_cancelled():
            raise AlreadyCancelled(reference)
        for line in order.lines:
            self.ledger.release(line.sku, line.quantity)
        order.mark_cancelled()
        self.repository.save(order)
        self.notifier.send_cancellation(order)

    def quote(self, reference: str, percent_off: int = 0) -> Money:
        """What this basket would cost, without committing to anything."""
        return total_for(self.repository.get(reference), percent_off)
