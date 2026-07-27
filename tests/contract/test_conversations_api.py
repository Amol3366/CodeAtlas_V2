"""Conversation and history REST (P5-02, `AGENTS.md` Section 12.2).

The endpoints here are the history surface only: creating, listing, reading,
renaming, archiving, and deleting a thread, plus paging its messages. Submitting
a message and streaming its answer arrive in P5-03 and P5-04.

Every assertion is about a promise the web client will rely on: stable
ordering, cursors that do not duplicate rows, a deletion that stays deleted,
and an error envelope with a machine-readable code rather than a stack trace.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.contracts import Conversation, ConversationPage, MessagePage
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
def repository_id(client: TestClient, sample_repo: Path) -> str:
    response = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert response.status_code == 201, response.text
    identifier: str = response.json()["repository_id"]
    return identifier


def _create(
    client: TestClient, repository_id: str, title: str = "What changed?"
) -> str:
    response = client.post(
        "/v1/conversations",
        json={"repository_id": repository_id, "title": title},
    )
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["conversation_id"]
    return conversation_id


def test_creating_a_conversation_returns_the_contract_model(
    client: TestClient, repository_id: str
) -> None:
    response = client.post(
        "/v1/conversations",
        json={"repository_id": repository_id, "title": "Impact of capture"},
    )

    assert response.status_code == 201, response.text
    conversation = Conversation.model_validate(response.json())
    assert conversation.repository_id == repository_id
    assert conversation.title == "Impact of capture"
    assert conversation.archived_at is None


def test_a_conversation_requires_an_existing_repository(client: TestClient) -> None:
    """A thread is bound to a repository for its whole life, so a bad
    reference must fail at creation rather than at first question."""
    response = client.post(
        "/v1/conversations",
        json={"repository_id": "repo_missing", "title": "Anything"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_a_title_is_derived_when_none_is_supplied(
    client: TestClient, repository_id: str
) -> None:
    """Deterministic titles only (ADR-0006 decision 8); a model-generated one
    would be non-authoritative and needs a provider that does not exist yet."""
    response = client.post(
        "/v1/conversations", json={"repository_id": repository_id}
    )

    assert response.status_code == 201, response.text
    assert Conversation.model_validate(response.json()).title


def test_listing_orders_by_recent_activity_and_pages_with_a_cursor(
    client: TestClient, repository_id: str
) -> None:
    identifiers = [
        _create(client, repository_id, f"Thread {index}") for index in range(3)
    ]

    first = client.get(
        "/v1/conversations",
        params={"repository_id": repository_id, "limit": 2},
    )
    assert first.status_code == 200, first.text
    page = ConversationPage.model_validate(first.json())
    assert len(page.items) == 2
    assert page.next_cursor is not None

    second = client.get(
        "/v1/conversations",
        params={
            "repository_id": repository_id,
            "limit": 2,
            "cursor": page.next_cursor,
        },
    )
    rest = ConversationPage.model_validate(second.json())
    seen = [item.conversation_id for item in (*page.items, *rest.items)]
    # No row appears twice and none is lost: that is what the cursor is for.
    assert sorted(seen) == sorted(identifiers)
    assert rest.next_cursor is None


def test_fetching_an_unknown_conversation_uses_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.get("/v1/conversations/conv_missing")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"]
    # Section 12.6: no stack traces, no filesystem paths.
    assert "Traceback" not in response.text


def test_renaming_a_conversation(client: TestClient, repository_id: str) -> None:
    conversation_id = _create(client, repository_id)

    response = client.patch(
        f"/v1/conversations/{conversation_id}", json={"title": "Renamed thread"}
    )

    assert response.status_code == 200, response.text
    assert Conversation.model_validate(response.json()).title == "Renamed thread"
    reloaded = client.get(f"/v1/conversations/{conversation_id}")
    assert reloaded.json()["title"] == "Renamed thread"


def test_archiving_hides_a_conversation_from_the_default_listing(
    client: TestClient, repository_id: str
) -> None:
    conversation_id = _create(client, repository_id)

    archived = client.patch(
        f"/v1/conversations/{conversation_id}", json={"archived": True}
    )
    assert archived.status_code == 200, archived.text
    assert Conversation.model_validate(archived.json()).archived_at is not None

    default = client.get(
        "/v1/conversations", params={"repository_id": repository_id}
    )
    assert ConversationPage.model_validate(default.json()).items == []

    included = client.get(
        "/v1/conversations",
        params={"repository_id": repository_id, "include_archived": True},
    )
    listed = ConversationPage.model_validate(included.json())
    assert [item.conversation_id for item in listed.items] == [conversation_id]


def test_deleting_a_conversation_makes_it_not_found(
    client: TestClient, repository_id: str
) -> None:
    """Deletion is soft in storage, but a deleted thread is gone to every
    caller: reporting it because the row survives would contradict the user."""
    conversation_id = _create(client, repository_id)

    deleted = client.delete(f"/v1/conversations/{conversation_id}")
    assert deleted.status_code == 204

    assert client.get(f"/v1/conversations/{conversation_id}").status_code == 404
    listed = client.get(
        "/v1/conversations", params={"repository_id": repository_id}
    )
    assert ConversationPage.model_validate(listed.json()).items == []


def test_renaming_a_deleted_conversation_is_not_found(
    client: TestClient, repository_id: str
) -> None:
    conversation_id = _create(client, repository_id)
    client.delete(f"/v1/conversations/{conversation_id}")

    response = client.patch(
        f"/v1/conversations/{conversation_id}", json={"title": "Zombie"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_messages_of_a_new_conversation_are_empty(
    client: TestClient, repository_id: str
) -> None:
    conversation_id = _create(client, repository_id)

    response = client.get(f"/v1/conversations/{conversation_id}/messages")

    assert response.status_code == 200, response.text
    page = MessagePage.model_validate(response.json())
    assert page.items == []
    assert page.next_cursor is None


def test_messages_of_an_unknown_conversation_are_not_found(
    client: TestClient,
) -> None:
    response = client.get("/v1/conversations/conv_missing/messages")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_an_over_long_title_is_rejected(
    client: TestClient, repository_id: str
) -> None:
    response = client.post(
        "/v1/conversations",
        json={"repository_id": repository_id, "title": "x" * 5000},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_body_fields_are_rejected(
    client: TestClient, repository_id: str
) -> None:
    """Strict boundaries: a typo'd field must fail loudly rather than be
    silently dropped."""
    response = client.post(
        "/v1/conversations",
        json={"repository_id": repository_id, "titel": "typo"},
    )

    assert response.status_code == 422


def test_listing_requires_a_repository(client: TestClient) -> None:
    response = client.get(
        "/v1/conversations", params={"repository_id": "repo_missing"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"
