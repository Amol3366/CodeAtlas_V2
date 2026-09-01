"""The predicate, proven on input whose answer is known by construction.

This row's count has already been wrong once. "Reversing the ranking fails 0 of
23" was true on 2026-08-15 and false two days later: `git log -S` puts q053 in
the very commit that added those 23, and ADR-0059 states it "becomes the first
post-2026-08-15 case to be reversal-sensitive". So it was 1 of 23.

A tool is committed so the next count is run rather than remembered, and the
tool's own predicate is exercised here on synthetic predictions -- the corpus
cannot produce a single-symbol answer *and* a multi-symbol one on demand, and a
predicate only ever run against inputs that satisfy it has demonstrated nothing
(ADR-0055).
"""

from __future__ import annotations

from codeatlas.evaluation.runner import QueryPrediction
from scripts.report_ranking_sensitivity import mutate


def _prediction(symbols: list[str]) -> QueryPrediction:
    return QueryPrediction(
        case_id="q000",
        ranked_symbols=symbols,
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=False,
        duration_ms=0.0,
    )


def test_reverse_inverts_the_symbol_order() -> None:
    assert mutate(_prediction(["a", "b", "c"]), "reverse").ranked_symbols == [
        "c",
        "b",
        "a",
    ]


def test_reverse_is_a_no_op_on_a_single_symbol() -> None:
    """Why the 2026-08-15 cases scored 0: most return exactly one symbol.

    This is the whole mechanism behind the row. A reversal cannot be detected
    by a case whose answer has nothing to reverse, so a corpus can grow its
    case count without growing its ranking coverage at all.
    """
    assert mutate(_prediction(["a"]), "reverse").ranked_symbols == ["a"]


def test_drop_top_removes_the_first_symbol() -> None:
    assert mutate(_prediction(["a", "b"]), "drop_top").ranked_symbols == ["b"]


def test_drop_top_on_a_single_symbol_leaves_an_empty_answer() -> None:
    """Which is why drop-top caught 18 of 23 where reverse caught 1."""
    assert mutate(_prediction(["a"]), "drop_top").ranked_symbols == []


def test_mutating_never_touches_the_original_prediction() -> None:
    """The instrument runs both mutations against one baseline prediction.

    If `mutate` aliased or mutated in place, the second mutation would be
    applied to the first one's output and the report would be nonsense.
    """
    original = _prediction(["a", "b", "c"])
    mutate(original, "reverse")
    mutate(original, "drop_top")
    assert original.ranked_symbols == ["a", "b", "c"]


def test_an_unknown_mutation_is_refused_rather_than_ignored() -> None:
    """A typo in a mutation name must not silently report zero sensitivity."""
    try:
        mutate(_prediction(["a"]), "reverese")
    except ValueError as error:
        assert "reverese" in str(error)
    else:  # pragma: no cover - the assertion below is the failure path
        raise AssertionError("an unknown mutation was accepted")
