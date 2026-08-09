"""A gate threshold must mean what it says.

`lexical_resolution` was gated at 0.90. It scores eight cases -- ten declare a
lexical intent, two sit on `malicious_unsupported` and are excluded by ADR-0024
-- so it can only take values that are multiples of 0.125. At eight cases,
0.90 required 8/8 and tolerated zero failures: arithmetically identical to 1.0
while reading as though one miss were acceptable.

ADR-0032 sets it to 1.0. These tests pin the reasoning rather than the number,
so a future author who lowers it has to confront what the corpus size actually
permits instead of picking a value that looks reasonable.
"""

from __future__ import annotations

import math
from pathlib import Path

from codeatlas.evaluation.dataset import (
    LEXICAL_INTENTS,
    SYMBOL_INTENTS,
    load_dataset,
)
from codeatlas.evaluation.engine_adapter import SUPPORTED_FIXTURES

DATASET_ROOT = Path("tests/evaluation/cases")
LEXICAL_THRESHOLD = 1.0
EXACT_SYMBOL_THRESHOLD = 0.98


def _scored(intents: frozenset[str] | set[str]) -> int:
    dataset = load_dataset(DATASET_ROOT)
    return sum(
        1
        for case in dataset.query_cases
        if case.intent in intents
        and case.expected_symbols
        and case.repository_fixture in SUPPORTED_FIXTURES
    )


def _scored_lexical_cases() -> int:
    return _scored(LEXICAL_INTENTS)


def test_the_lexical_gate_tolerates_no_failures_at_this_corpus_size() -> None:
    """The claim ADR-0032 rests on, asserted rather than assumed."""
    scored = _scored_lexical_cases()
    required = math.ceil(LEXICAL_THRESHOLD * scored - 1e-9)

    assert scored == 8
    assert required == scored, "the threshold must require every scored case"


def test_the_replaced_threshold_selected_the_same_cases() -> None:
    """0.90 was not looser than 1.0 here, which is why this is not a tightening.

    If this ever fails, the corpus has grown and the two values have genuinely
    separated -- at which point the threshold is a real decision again rather
    than a spelling choice, and ADR-0032's reasoning no longer applies.
    """
    scored = _scored_lexical_cases()

    assert math.ceil(0.90 * scored - 1e-9) == math.ceil(1.0 * scored - 1e-9)


def test_the_exact_symbol_gate_is_stricter_than_its_stated_target() -> None:
    """Section 19.3 declares >= 98%. At 27 cases that enforces 27/27.

    Kept at 0.98 rather than restated as 1.0 (ADR-0033). Unlike
    `lexical_resolution`'s provisional 0.90, this is a release commitment that
    becomes expressible once the corpus reaches roughly fifty cases; restating
    it would tighten a product promise to match an artifact of corpus size.

    Being stricter than the target is safe -- nothing violating 98% can pass.
    This test exists so the discrepancy is visible rather than surprising.
    """
    scored = _scored(SYMBOL_INTENTS)
    required = math.ceil(EXACT_SYMBOL_THRESHOLD * scored - 1e-9)

    assert scored == 27
    assert required == scored, "0.98 tolerates no failures at this corpus size"


def test_the_exact_symbol_target_becomes_meaningful_on_a_larger_corpus() -> None:
    """The condition under which 0.98 starts expressing what it says.

    Fails deliberately once the corpus is large enough for 0.98 and 1.0 to
    differ -- at which point the gate stops being stricter than its target and
    ADR-0033's reasoning no longer needs stating.
    """
    scored = _scored(SYMBOL_INTENTS)

    assert math.ceil(EXACT_SYMBOL_THRESHOLD * scored - 1e-9) == math.ceil(
        1.0 * scored - 1e-9
    ), "0.98 and 1.0 have separated; revisit ADR-0033"

    fifty = 50
    assert math.ceil(EXACT_SYMBOL_THRESHOLD * fifty - 1e-9) < fifty


def test_a_lower_threshold_would_have_to_be_a_multiple_of_the_case_size() -> None:
    """Any value between 0.875 and 1.0 is indistinguishable from 1.0.

    Recorded so a future 0.95 -- which would look like a considered relaxation
    and would change nothing -- is caught here rather than shipped.
    """
    scored = _scored_lexical_cases()
    reachable = {index / scored for index in range(scored + 1)}

    for invented in (0.90, 0.92, 0.95, 0.99):
        assert invented not in reachable
        assert math.ceil(invented * scored - 1e-9) == scored
