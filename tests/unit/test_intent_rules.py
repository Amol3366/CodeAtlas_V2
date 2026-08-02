"""Deterministic intent classification (P5-03, ADR-0006 decision 3).

Intent is decided by rules, in a fixed order, with no model involved. The rules
are versioned because a stored run records which policy answered it: if the
rules change, an old run must not appear to have been answered by the new ones.

Every case here states the phrasing a user would actually type. The point is
not that the rules are clever — they are deliberately not — but that they are
predictable and that the fallback is honest.
"""

from __future__ import annotations

import pytest

from codeatlas.conversations.intent import (
    MAX_QUERY_CHARACTERS,
    RETRIEVAL_POLICY_VERSION,
    Intent,
    classify,
)
from codeatlas.domain.errors import QueryTooLongError


def test_the_policy_version_is_recorded() -> None:
    """A run stores this; changing the rules without changing the version
    would make old runs claim to have used rules they never saw."""
    assert RETRIEVAL_POLICY_VERSION == "5.2"
    assert classify("PaymentService.capture").policy_version == "5.2"


@pytest.mark.parametrize("text", ["Hi", "hello!", "hey there", "good morning"])
def test_greetings_do_not_route_to_repository_search(text: str) -> None:
    result = classify(text)
    assert result.intent is Intent.GREETING
    assert result.target == text


@pytest.mark.parametrize(
    "text",
    [
        "tell me about prelegal project",
        "what is this repository?",
        "summarize the codebase",
        "give me an overview of the project",
    ],
)
def test_project_overview_questions_use_the_overview_intent(text: str) -> None:
    result = classify(text)
    assert result.intent is Intent.PROJECT_OVERVIEW
    assert result.target == " ".join(text.split())


@pytest.mark.parametrize(
    "text",
    [
        "PaymentService.capture",
        "capture",
        "src/payments/service.py",
    ],
)
def test_a_bare_symbol_or_path_resolves_exactly_first(text: str) -> None:
    """Exact resolution precedes every broader channel (Section 10.2)."""
    result = classify(text)
    assert result.intent is Intent.EXACT_SYMBOL
    assert result.target == text


@pytest.mark.parametrize(
    "text",
    [
        "who calls PaymentService.capture",
        "who calls PaymentService.capture?",
        "what calls PaymentService.capture",
        "callers of PaymentService.capture",
        "Who Calls PaymentService.capture",
    ],
)
def test_caller_phrasing_routes_to_the_graph(text: str) -> None:
    result = classify(text)
    assert result.intent is Intent.CALLERS
    assert result.target == "PaymentService.capture"


def test_callee_phrasing_is_distinct_from_caller_phrasing() -> None:
    """Caller and callee phrasing are opposite directions; a rule
    that confused them would report the dependency graph backwards."""
    assert classify("what does PaymentService.capture call").intent is Intent.CALLEES
    assert classify("who calls PaymentService.capture").intent is Intent.CALLERS


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("what does capture depend on", Intent.DEPENDENCIES),
        ("dependencies of capture", Intent.DEPENDENCIES),
        ("tests for capture", Intent.TESTS),
        ("what tests capture", Intent.TESTS),
        ("docs for capture", Intent.DOCUMENTS),
        ("documentation for capture", Intent.DOCUMENTS),
        ("trace capture", Intent.TRACE),
        ("trace the flow from capture", Intent.TRACE),
    ],
)
def test_each_graph_intent_has_its_phrasing(text: str, intent: Intent) -> None:
    result = classify(text)
    assert result.intent is intent
    assert result.target == "capture"


@pytest.mark.parametrize(
    "text",
    [
        "what changed",
        "what changed?",
        "show likely impact",
        "what might break",
    ],
)
def test_change_phrasing_routes_to_change_analysis(text: str) -> None:
    result = classify(text)
    assert result.intent is Intent.CHANGE


def test_free_text_falls_back_to_lexical_search() -> None:
    """The fallback is a real channel, not an apology: a question the rules do
    not recognize is still answered from the index."""
    result = classify("how does idempotency work in this repository")
    assert result.intent is Intent.TEXT
    assert result.target == "how does idempotency work in this repository"


def test_classification_is_stable_across_calls() -> None:
    first = classify("who calls PaymentService.capture")
    second = classify("who calls PaymentService.capture")
    assert first == second


def test_surrounding_whitespace_does_not_change_the_intent() -> None:
    assert classify("  who calls capture  ").intent is Intent.CALLERS
    assert classify("  who calls capture  ").target == "capture"


def test_an_empty_question_is_refused() -> None:
    with pytest.raises(ValueError):
        classify("   ")


def test_an_over_long_question_is_refused_rather_than_truncated() -> None:
    """Truncating would answer a question the user did not ask."""
    with pytest.raises(QueryTooLongError):
        classify("x" * (MAX_QUERY_CHARACTERS + 1))
