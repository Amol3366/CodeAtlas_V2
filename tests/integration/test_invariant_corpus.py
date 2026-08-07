"""The committed invariant corpus, run in-process.

`scripts/check_invariants.py --check` is the gate. This is the same check
without the artifact comparison, so a plain `uv run pytest` catches a broken
invariant too. It holds no expectations of its own -- it asserts only that
every case in the corpus held -- so it cannot be weakened without weakening
the corpus.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.contracts import GapReasonCode
from codeatlas.evaluation.invariants import check_corpus, load_corpus

CORPUS = Path("tests/evaluation/invariant_cases")


def test_every_adr_0016_invariant_holds() -> None:
    result = check_corpus(load_corpus(CORPUS))

    broken = [
        f"{item.case_id}: {'; '.join(item.failures)}"
        for item in result.results
        if not item.held
    ]
    assert not broken, "\n".join(broken)


def test_the_corpus_covers_both_weak_derivation_paths() -> None:
    # The gap this whole corpus exists to close. If someone deletes the
    # fixture and helper cases, every other assertion here still passes.
    corpus = load_corpus(CORPUS)
    expected = {
        reason for case in corpus.cases for reason in case.expect_gap_reasons.values()
    }

    assert GapReasonCode.FIXTURE_MEDIATED_ONLY in expected
    assert GapReasonCode.HELPER_MEDIATED_ONLY in expected


def test_the_corpus_still_proves_a_strict_edge_closes_a_gap() -> None:
    corpus = load_corpus(CORPUS)

    assert any(case.expect_not_gaps for case in corpus.cases)
