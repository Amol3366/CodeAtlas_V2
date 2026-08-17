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


def test_the_exact_symbol_gate_now_expresses_its_stated_target() -> None:
    """Section 19.3 declares >= 98%, and from 50 cases on it finally means that.

    **This assertion is the inverse of the one it replaces**, and the change is
    the point rather than a relaxation. At 27 cases `ceil(0.98 * 27) == 27`, so
    the gate silently required 27/27 while reading as though one miss were
    acceptable; ADR-0033 kept 0.98 anyway, because restating a Section 19.3
    release commitment as 1.0 would have tightened a product promise to match an
    artifact of corpus size, and recorded that the real fix was corpus size.

    The corpus reached 50 on 2026-08-15 and the two values separated. The old
    assertion failed at that moment, exactly as the pair of tripwires below it
    was written to do.

    It is **51** since ADR-0059 added q065, and the margin is unchanged: one
    miss scores 0.9804 and still clears 0.98, two score 0.9608 and fail. The
    exact counts are asserted rather than only the inequality, because a
    denominator that moves without anyone noticing is how ADR-0017 hid 16
    unscored cases for four phases -- so a change here should have to be
    deliberate.
    """
    scored = _scored(SYMBOL_INTENTS)
    required = math.ceil(EXACT_SYMBOL_THRESHOLD * scored - 1e-9)

    assert scored == 51
    assert required == 50
    assert required < scored, "0.98 must now tolerate exactly one miss"


def test_the_exact_symbol_target_has_separated_from_one_point_zero() -> None:
    """ADR-0033's condition, now discharged.

    Its predecessor asserted that 0.98 and 1.0 selected the *same* number of
    cases and was documented as failing deliberately once that stopped being
    true. It stopped being true. Keeping the tripwire pointed the other way
    means a future shrinkage of the corpus -- or a fixture quietly dropped from
    `SUPPORTED_FIXTURES`, which ADR-0017 records happening for four phases --
    puts the illusion back and fails here rather than passing quietly.
    """
    scored = _scored(SYMBOL_INTENTS)

    assert math.ceil(EXACT_SYMBOL_THRESHOLD * scored - 1e-9) != math.ceil(
        1.0 * scored - 1e-9
    ), "0.98 and 1.0 have collapsed together again; the corpus shrank"


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
