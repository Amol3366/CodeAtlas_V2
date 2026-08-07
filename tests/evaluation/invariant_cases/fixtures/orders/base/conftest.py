# `import orders` + `orders.Order()` rather than `from orders import Order`:
# the strict import-and-call pass matches an IMPORTS relation's target symbol
# against a CALLS target in the same file. A module import only names the
# module as imported, not `Order` itself, so this fixture cannot accidentally
# satisfy the strict pass on its own -- it only produces the CALLS edge that
# the fixture-mediation pass follows.
import pytest

import orders


@pytest.fixture
def store():
    return orders.Order()
