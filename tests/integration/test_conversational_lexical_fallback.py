"""A conversational question must not return nothing.

`build_match_expression` joins every term with AND, including stopwords. That is
right for a targeted lookup — `service.port` should not match every file
mentioning `port` — and wrong for the sentence a person types into a chat box,
because no chunk contains all twelve words of "How do we stop two shoppers
buying the last one of something?". The result was zero evidence for every
natural-language question, on the surface most likely to receive one.

The fix is a *fallback*, and the shape matters more than the behaviour: the
strict AND query still runs first, and the broader reading is tried only when
it returned nothing. A query that finds something today finds exactly the same
thing tomorrow, which is what lets this land without moving a single committed
baseline.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


class Fixture(NamedTuple):
    services: object
    repository_id: str


@pytest.fixture()
def fixture(tmp_path: Path, sample_repo: Path) -> Iterator[Fixture]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        built.indexing.index(repository.repository_id)
        yield Fixture(built, repository.repository_id)


def _search(fixture: Fixture, query: str):  # type: ignore[no-untyped-def]
    return fixture.services.search.search_text(  # type: ignore[attr-defined]
        SearchRequest(
            repository_id=fixture.repository_id,
            query=query,
            request_id="req_1",
        )
    )


def test_a_conversational_question_finds_something(fixture: Fixture) -> None:
    """The defect this file exists for. Every word of the sentence ANDed
    together matches no chunk, so the user got nothing at all."""
    response = _search(fixture, "How does the service capture a payment?")

    assert response.evidence


def test_the_relaxed_pass_is_reported_as_a_warning(fixture: Fixture) -> None:
    """A broader reading answered a different question than the one asked, and
    Section 4.1 says to say so rather than present it as an exact match."""
    response = _search(fixture, "How does the service capture a payment?")

    assert "LEXICAL_QUERY_RELAXED" in response.warnings


def test_a_query_that_already_matched_is_untouched(fixture: Fixture) -> None:
    """The property that keeps every committed baseline valid: the fallback
    only ever runs when the strict pass found nothing, so a query with results
    cannot change."""
    response = _search(fixture, "capture")

    assert response.evidence
    assert "LEXICAL_QUERY_RELAXED" not in response.warnings


def test_a_multi_word_query_that_matched_strictly_is_untouched(
    fixture: Fixture,
) -> None:
    """`Order flow`-shaped lookups are the reason the strict pass runs first:
    ANDing the words is what makes them precise."""
    response = _search(fixture, "capture key")

    assert response.evidence
    assert "LEXICAL_QUERY_RELAXED" not in response.warnings


def test_a_question_of_pure_stopwords_still_finds_nothing(
    fixture: Fixture,
) -> None:
    """The fallback widens a real question; it must not turn a contentless one
    into a tour of the repository."""
    response = _search(fixture, "how do we do it")

    assert response.evidence == []


def test_a_question_about_nothing_in_the_repository_finds_nothing(
    fixture: Fixture,
) -> None:
    """Abstention still has to be reachable, or the channel would answer every
    question with something."""
    response = _search(fixture, "How is the kubernetes ingress gateway rotated?")

    assert response.evidence == []
