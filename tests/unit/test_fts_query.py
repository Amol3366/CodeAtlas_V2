"""The validated FTS5 query builder.

User text never reaches FTS5 as syntax. Everything here is about that one
property: whatever a user types comes out as quoted literal terms or as a
bounded error, and never as an operator, a wildcard, or a parse failure.
"""

from __future__ import annotations

import pytest

from codeatlas.domain.errors import SearchQueryError
from codeatlas.retrieval.fts_query import (
    MAX_SEARCH_QUERY_LENGTH,
    MAX_SEARCH_TERMS,
    build_match_expression,
)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", '"', "*", "()", "^" * 50, "x" * (MAX_SEARCH_QUERY_LENGTH + 1)],
)
def test_unusable_queries_are_rejected(raw: str) -> None:
    with pytest.raises(SearchQueryError):
        build_match_expression(raw)


def test_terms_are_quoted_and_joined_with_and() -> None:
    assert build_match_expression("payment service") == '"payment" AND "service"'


def test_identifier_characters_survive() -> None:
    assert build_match_expression("PaymentService.capture") == (
        '"paymentservice.capture"'
    )


def test_underscores_and_hyphens_survive() -> None:
    assert build_match_expression("line-length max_bytes") == (
        '"line-length" AND "max_bytes"'
    )


def test_fts_operators_are_neutralized() -> None:
    expression = build_match_expression("payment OR service*")

    assert "OR " not in expression.replace('"OR"', "")
    assert "*" not in expression
    assert expression == '"payment" AND "or" AND "service"'


def test_a_near_query_becomes_literal_terms() -> None:
    assert build_match_expression("NEAR(a b, 100000)") == (
        '"near" AND "a" AND "b" AND "100000"'
    )


def test_quotes_cannot_escape_the_literal() -> None:
    expression = build_match_expression('say "hi"')

    assert expression == '"say" AND "hi"'
    # Every quote in the output is a delimiter this builder emitted itself.
    assert expression.count('"') % 2 == 0


def test_punctuation_only_terms_are_dropped() -> None:
    assert build_match_expression("drop -- table") == '"drop" AND "table"'


def test_term_count_is_capped() -> None:
    # Short terms on purpose: this asserts the term cap, not the length cap.
    expression = build_match_expression(" ".join(f"t{index}" for index in range(40)))
    assert expression.count(" AND ") == MAX_SEARCH_TERMS - 1


def test_the_builder_is_deterministic() -> None:
    assert build_match_expression("Payment Service") == build_match_expression(
        "payment  service"
    )


def test_unicode_is_normalized_before_matching() -> None:
    # U+00E9 and "e" + U+0301 are the same character in NFC.
    assert build_match_expression("café") == build_match_expression("café")
