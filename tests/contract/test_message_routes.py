"""Message-scoped routes are addressed as messages (`AGENTS.md` Section 12.2).

`retry` and `feedback` act on a message id and carry no conversation id, so
nesting them under `/v1/conversations/` scoped them by a resource they never
name. `cancel` — the third operation on the same run lifecycle — has always
sat at `/v1/message-runs/{run_id}/cancel`, so the nesting was also inconsistent
with its own sibling. ADR-0068 moved the code to the contract rather than the
contract to the code.

Each pair is two-sided on purpose. Registering the new path while leaving the
old one is not what was ruled, and a one-sided test would permit it — the same
reasoning ADR-0066's inverted xfail and the working-tree line-ending guard use.

The discriminator is the error *code*, not the status. Both shapes answer 404:
an unregistered `/v1` path returns `INVALID_REQUEST` ("No such endpoint.") from
the app-level handler P6-08 added, while a registered route reached with an
unknown id returns `MESSAGE_NOT_FOUND` from the service. Asserting the status
alone would pass whether or not the route existed.

No message is created. These are assertions about addressing, and reaching the
handler is the whole of what they check — which is also why an unknown id is
the right input rather than an incidental one.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

UNKNOWN_MESSAGE = "msg_does_not_exist"


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path)) as test_client:
        yield test_client


def _error_code(client: TestClient, path: str, **kwargs: object) -> str:
    response = client.post(path, **kwargs)  # type: ignore[arg-type]
    assert response.status_code == 404, response.text
    code: str = response.json()["error"]["code"]
    return code


def test_a_message_is_retried_at_its_own_path(client: TestClient) -> None:
    assert (
        _error_code(client, f"/v1/messages/{UNKNOWN_MESSAGE}/retry")
        == "MESSAGE_NOT_FOUND"
    )


def test_the_conversation_nested_retry_path_is_gone(client: TestClient) -> None:
    assert (
        _error_code(client, f"/v1/conversations/messages/{UNKNOWN_MESSAGE}/retry")
        == "INVALID_REQUEST"
    )


def test_feedback_is_submitted_at_the_messages_own_path(client: TestClient) -> None:
    assert (
        _error_code(
            client,
            f"/v1/messages/{UNKNOWN_MESSAGE}/feedback",
            json={"rating": "up"},
        )
        == "MESSAGE_NOT_FOUND"
    )


def test_the_conversation_nested_feedback_path_is_gone(client: TestClient) -> None:
    assert (
        _error_code(
            client,
            f"/v1/conversations/messages/{UNKNOWN_MESSAGE}/feedback",
            json={"rating": "up"},
        )
        == "INVALID_REQUEST"
    )
