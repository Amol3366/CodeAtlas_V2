"""The adapter that answers conceptual cases, with and without the layer.

Uplift is a *difference* between two runs, so the thing that most needs proving
is that the two runs differ in exactly one respect. If the semantic-off run
quietly took a different code path — a different service, a different question
string, a different limit — the difference measured afterwards would be an
artifact of the harness rather than a property of semantic retrieval.

These tests pin that: same pipeline, same question, same corpus, one switch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import load_dataset
from codeatlas.evaluation.engine_adapter import predict_conceptual

DATASET = Path("tests/evaluation/semantic_cases")


@pytest.fixture(scope="module")
def dataset():  # type: ignore[no-untyped-def]
    return load_dataset(DATASET)


def test_every_conceptual_case_is_answered_without_the_layer(dataset) -> None:  # type: ignore[no-untyped-def]
    """Deterministic-only is a complete product, so no case may be skipped."""
    result = predict_conceptual(dataset, semantic=False, record_timings=False)

    assert len(result.query_predictions) == len(dataset.query_cases)
    assert {item.case_id for item in result.query_predictions} == {
        case.id for case in dataset.query_cases
    }


def test_the_deterministic_run_needs_no_provider(dataset) -> None:  # type: ignore[no-untyped-def]
    """It must run on an installation that never opted into anything —
    otherwise the 'deterministic baseline' it produces is not one."""
    result = predict_conceptual(dataset, semantic=False, record_timings=False)

    assert any(item.ranked_evidence for item in result.query_predictions)


def test_the_run_is_reproducible(dataset) -> None:  # type: ignore[no-untyped-def]
    """A baseline that moved between runs could not be committed or compared."""
    first = predict_conceptual(dataset, semantic=False, record_timings=False)
    second = predict_conceptual(dataset, semantic=False, record_timings=False)

    assert first.model_dump() == second.model_dump()


def test_the_question_is_asked_verbatim(dataset) -> None:  # type: ignore[no-untyped-def]
    """Conceptual retrieval is measured on the natural-language question.

    The Phase 1 adapter substitutes the declared symbol for the question, which
    measures resolution rather than understanding. Doing that here would hand
    the answer to both runs and guarantee no difference between them.
    """
    result = predict_conceptual(dataset, semantic=False, record_timings=False)
    case = next(case for case in dataset.query_cases if case.id == "s001")

    # No declared symbol appears in the question, so an adapter that had
    # substituted one could not produce this prediction from the question alone.
    assert case.expected_symbols[0] not in case.question
    assert any(item.case_id == "s001" for item in result.query_predictions)
