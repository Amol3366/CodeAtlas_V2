"""Failures the ordering domain can express."""


class OrderError(Exception):
    """Base class for every failure raised by the ordering domain."""


class OrderNotFound(OrderError):
    """No order exists under the requested reference."""


class LineItemInvalid(OrderError):
    """A line was rejected before it could join an order."""


class OutOfStock(OrderError):
    """The warehouse cannot satisfy the requested quantity."""


class AlreadyCancelled(OrderError):
    """The order was cancelled earlier and cannot be cancelled twice."""


class PaymentDeclined(OrderError):
    """The card issuer refused the charge."""
