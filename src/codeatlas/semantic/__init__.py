"""The optional semantic layer.

Nothing outside this package may import an optional dependency, and nothing
inside it may import one at module scope. Both halves of that rule matter: the
first keeps the deterministic product free of the extras, and the second means
importing this package on a machine that never installed them is free and
silent rather than an ImportError.
"""
