"""Evidence recall is measured by containment, per ADR-0003.

`primary_evidence_recall_at_10` compares `snapshot:path:start:end` by exact
string equality, so a citation one line longer than the gold range scores as a
total miss. On the Phase 7 conceptual corpus that is four of its five misses:
s001 and s012 return the right evidence at **rank 1**, s008 at rank 2, s013 at
rank 4, and every one is recorded as not found.

ADR-0003 already ruled that containment is the right granularity for evidence,
and ADR-0023 moved the evidence *gate* from `valid_evidence_rate` to
`containing_evidence_rate` on exactly that reasoning. The recall metric was
never moved with it.

The correction follows ADR-0003's own precedent: the exact-match number stays
reported and keeps its meaning, and a containing variant is added beside it.
Redefining the historical metric in place would silently change what six
baselines mean.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.evaluation.dataset import QueryCase, load_dataset
from codeatlas.evaluation.runner import (
    EvidencePrediction,
    QueryPrediction,
    score_query_case,
)

DATASET_ROOT = Path("tests/evaluation/cases")


def _predict(start: int, end: int) -> QueryPrediction:
    """q001 expects `src/payments/service.py:3-11` in `python-v1`."""
    return QueryPrediction(
        case_id="q001",
        ranked_symbols=["PaymentService"],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id="python-v1",
                file_path="src/payments/service.py",
                start_line=start,
                end_line=end,
            )
        ],
        relation_paths=[],
        claims=[],
        abstained=False,
        duration_ms=1.0,
    )


def _case() -> QueryCase:
    return load_dataset(DATASET_ROOT).query_cases[0]


def test_a_citation_one_line_longer_counts_as_found() -> None:
    """The s012 shape: right section, one extra line, currently a total miss."""
    score = score_query_case(_case(), _predict(3, 12))

    assert score.evidence_containing.recall == 1.0
    assert score.evidence.recall == 0.0, (
        "the exact-match metric must keep its meaning; if this flips, six "
        "baselines silently change what they report"
    )


def test_exact_agreement_counts_for_both() -> None:
    """Containment is a superset of exact agreement, never a substitute."""
    score = score_query_case(_case(), _predict(3, 11))

    assert score.evidence_containing.recall == 1.0
    assert score.evidence.recall == 1.0


def test_a_citation_that_clips_the_answer_counts_for_neither() -> None:
    """ADR-0003's directional rule, pinned so this cannot quietly widen.

    A prediction that merely overlaps — omitting part of the expected range —
    has not proven the claim. Without this test, 'containment' could drift into
    'overlap' and the metric would start rewarding partial citations.
    """
    clipped = score_query_case(_case(), _predict(5, 9))
    assert clipped.evidence_containing.recall == 0.0
    assert clipped.evidence.recall == 0.0

    straddling = score_query_case(_case(), _predict(1, 8))
    assert straddling.evidence_containing.recall == 0.0


def test_a_citation_in_another_file_counts_for_neither() -> None:
    """Containment is file-scoped: line numbers alone mean nothing."""
    prediction = QueryPrediction(
        case_id="q001",
        ranked_symbols=["PaymentService"],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id="python-v1",
                file_path="src/payments/other.py",
                start_line=1,
                end_line=99,
            )
        ],
        relation_paths=[],
        claims=[],
        abstained=False,
        duration_ms=1.0,
    )

    score = score_query_case(_case(), prediction)

    assert score.evidence_containing.recall == 0.0
