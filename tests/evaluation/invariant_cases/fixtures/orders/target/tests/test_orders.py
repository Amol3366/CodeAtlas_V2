# Imports are deliberately *local* to each function rather than shared at
# module scope. A shared top-level import would be visible to every test in
# the file, and then any test that merely calls the corresponding helper would
# look like it both imports and calls the symbol directly, collapsing
# helper-mediated into strict.
def test_total(store):
    assert store is not None


def _build():
    # `import orders` + `orders.total(...)`, for the same reason as the root
    # fixture above: it must produce a CALLS edge without also satisfying the
    # strict import-and-call pass on `_build` itself.
    import orders

    return orders.total({'amount': 1})


def test_via_helper():
    _build()


def test_direct():
    from orders import unused_helper

    assert unused_helper() == 0
