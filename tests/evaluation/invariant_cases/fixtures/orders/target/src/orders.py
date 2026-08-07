class Order:
    kind = 'sales'

    def __init__(self):
        self.amount = 0


def total(order):
    return order.amount + 1


def unused_helper():
    return 1


def audit():
    return "changed"
