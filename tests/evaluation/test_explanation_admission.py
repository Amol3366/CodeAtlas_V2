"""The P7-11 explanation admission logic.

**What is tested here, and what deliberately is not.** The A/B itself answers
every corpus case through a real Ollama model, so running it inside the suite
would make the suite depend on a service that is optional by design and absent
on most machines. That orchestration is verified by running it and recording
the artifact (`docs/evaluation/explanation-phase-7.{json,md}`), which names the
model and the hardware it ran on.

What is tested here is the logic that decides what the artifact says: whether
generated prose stated a forbidden claim, and how that becomes a decision. That
logic is pure, and it is the part that would silently start lying if it broke.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from scripts.run_phase7_explanation_ab import _prose_safety, _reason


def _dataset(*cases: tuple[str, list[str]]) -> Any:
    return SimpleNamespace(
        query_cases=[
            SimpleNamespace(id=case_id, forbidden_claims=forbidden)
            for case_id, forbidden in cases
        ]
    )


def _predictions(*rows: tuple[str, str]) -> Any:
    return SimpleNamespace(
        query_predictions=[
            SimpleNamespace(case_id=case_id, answer_summary=summary)
            for case_id, summary in rows
        ]
    )


def test_clean_prose_reports_no_violation() -> None:
    result = _prose_safety(
        _dataset(("q1", ["The database guarantees exactly-once execution."])),
        _predictions(("q1", "Idempotency is enforced by a claim table.")),
    )

    assert result["violations"] == 0
    assert result["cases_with_forbidden_claims"] == 1
    assert result["offenders"] == []


def test_a_forbidden_claim_in_generated_prose_is_caught() -> None:
    """The one surface generation can introduce an unsupported statement on.

    The retrieval suite checks `forbidden_claims` against structured claims,
    which a model never writes — so without this check a model could state a
    forbidden thing in prose and every metric would still read clean.
    """
    result = _prose_safety(
        _dataset(("q1", ["The database guarantees exactly-once execution"])),
        _predictions(
            (
                "q1",
                "The database guarantees exactly-once execution, so retries"
                " are safe.",
            )
        ),
    )

    assert result["violations"] == 1
    assert result["offenders"][0]["case_id"] == "q1"


def test_the_check_is_exact_substring_and_misses_a_paraphrase() -> None:
    """A deliberate record of how weak this signal is.

    `contains_forbidden_claim` casefolds and collapses whitespace; it does not
    stem, strip punctuation, or compare meaning. A model that paraphrases a
    forbidden statement passes. "The prose stated no forbidden claim" is
    therefore evidence of *not repeating a declared sentence*, not evidence of
    factual safety, and the artifact must not be read as the latter.
    """
    result = _prose_safety(
        _dataset(("q1", ["The database guarantees exactly-once execution"])),
        _predictions(("q1", "Exactly-once delivery is assured by the database.")),
    )

    assert result["violations"] == 0


def test_cases_declaring_no_forbidden_claim_are_not_counted() -> None:
    result = _prose_safety(
        _dataset(("q1", []), ("q2", ["never true"])),
        _predictions(("q1", "anything at all"), ("q2", "something else")),
    )

    assert result["cases_with_forbidden_claims"] == 1


def test_the_decision_names_a_violation_when_there_is_one() -> None:
    reason = _reason(False, {"violations": 2})

    assert "2 forbidden" in reason


def test_the_decision_says_prose_was_clean_without_overstating_it() -> None:
    reason = _reason(False, {"violations": 0})

    assert "repeated no declared forbidden sentence" in reason
    # The weakness of the check is stated wherever its result is.
    assert "paraphrase" in reason


def test_a_moved_metric_is_reported_as_a_leaked_boundary() -> None:
    """Every scored metric is invariant under generation by construction.

    If one moves, the summary-only guarantee has broken, and the artifact must
    say so rather than quietly recording it as uplift.
    """
    reason = _reason(True, {"violations": 0})

    assert "leaked" in reason
