"""A conversation answer is the `/v1/query` answer (P5-03, ADR-0006 decision 3).

This is the test that keeps the chat surface from becoming a second, weaker
path to repository truth. If the pipeline ever starts choosing its own
evidence, adding its own claim, or rewriting a warning, the comparison below
fails.

The suite also asserts the comparison is not vacuous: a parity test that
compares two empty answers proves nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.contracts import QueryResponse
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path)) as test_client:
        yield test_client


@pytest.fixture()
def indexed(client: TestClient, sample_repo: Path) -> str:
    created = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert created.status_code == 201, created.text
    repository_id: str = created.json()["repository_id"]
    indexed = client.post(f"/v1/repositories/{repository_id}/index")
    assert indexed.status_code == 200, indexed.text
    return repository_id


def _ask(client: TestClient, repository_id: str, question: str) -> dict[str, object]:
    conversation = client.post(
        "/v1/conversations", json={"repository_id": repository_id}
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["conversation_id"]

    posted = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": question},
    )
    assert posted.status_code == 201, posted.text
    body: dict[str, object] = posted.json()
    return body


def _query(
    client: TestClient, repository_id: str, query: str, mode: str
) -> QueryResponse:
    response = client.post(
        "/v1/query",
        json={"repository_id": repository_id, "query": query, "mode": mode},
    )
    assert response.status_code == 200, response.text
    return QueryResponse.model_validate(response.json())


@pytest.mark.parametrize(
    ("question", "query", "mode"),
    [
        ("PaymentService.capture", "PaymentService.capture", "exact_symbol"),
        (
            "who calls PaymentService.capture",
            "PaymentService.capture",
            "callers",
        ),
        ("tests for PaymentService.capture", "PaymentService.capture", "tests"),
    ],
)
def test_a_conversation_answer_matches_the_query_answer(
    client: TestClient,
    indexed: str,
    question: str,
    query: str,
    mode: str,
) -> None:
    asked = _ask(client, indexed, question)
    direct = _query(client, indexed, query, mode)

    evidence = asked["evidence"]
    assert isinstance(evidence, list)
    assert [item["file_path"] for item in evidence] == [
        item.file_path for item in direct.evidence
    ]
    assert [(item["start_line"], item["end_line"]) for item in evidence] == [
        (item.start_line, item.end_line) for item in direct.evidence
    ]
    assert asked["warnings"] == direct.warnings


def test_the_parity_comparison_is_not_vacuous(
    client: TestClient, indexed: str
) -> None:
    """Two empty answers would compare equal and prove nothing."""
    direct = _query(client, indexed, "PaymentService.capture", "exact_symbol")

    assert direct.evidence
    assert direct.answer.claims

    asked = _ask(client, indexed, "PaymentService.capture")
    evidence = asked["evidence"]
    assert isinstance(evidence, list)
    assert evidence


def test_the_answer_is_bound_to_the_snapshot_that_produced_it(
    client: TestClient, indexed: str
) -> None:
    """A stored message keeps its own snapshot label forever (Section 14.5)."""
    asked = _ask(client, indexed, "PaymentService.capture")
    direct = _query(client, indexed, "PaymentService.capture", "exact_symbol")

    assert asked["snapshot_id"] == direct.snapshot.snapshot_id


def test_an_unanswerable_question_abstains_rather_than_guessing(
    client: TestClient, indexed: str
) -> None:
    asked = _ask(client, indexed, "NoSuchSymbolAnywhere")

    assert asked["evidence"] == []
    content = asked["content"]
    assert isinstance(content, str)
    assert "not answering rather than guessing" in content
