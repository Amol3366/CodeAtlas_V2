"""Accept-then-stream submission over HTTP (P6-STREAM, ADR-0008).

Phase 5 executed the run inline and returned it finished, which meant no run
was ever in flight and `Thread` never opened a stream. `CLAUDE.md` Section 12.2
asks for the opposite — "Return IDs immediately, then stream or poll status" —
and these tests pin that behavior.

The load-bearing one is `test_the_stream_is_live_when_submission_returns`. A
client submits and *immediately* opens the stream; if the channel is only
created once the background thread happens to start, the client is told there
is no run and silently falls back to polling. Opening the channel before
returning is therefore part of the contract, not an implementation detail.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_TIMEOUT_SECONDS = 20.0


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path, watch=False)) as test_client:
        yield test_client


@pytest.fixture()
def conversation(client: TestClient, sample_repo: Path) -> str:
    created = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert created.status_code == 201, created.text
    repository_id = created.json()["repository_id"]
    indexed = client.post(f"/v1/repositories/{repository_id}/index")
    assert indexed.status_code == 200, indexed.text
    opened = client.post("/v1/conversations", json={"repository_id": repository_id})
    assert opened.status_code == 201, opened.text
    conversation_id: str = opened.json()["conversation_id"]
    return conversation_id


def _submit(
    client: TestClient, conversation_id: str, text: str = "What is capture?"
) -> Response:
    response: Response = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": text}
    )
    return response


def _await_message(
    client: TestClient, conversation_id: str, message_id: str
) -> dict[str, Any]:
    """Poll until the assistant message reaches a terminal status."""
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    terminal = {"complete", "failed", "cancelled"}
    while time.monotonic() < deadline:
        page = client.get(f"/v1/conversations/{conversation_id}/messages")
        assert page.status_code == 200, page.text
        for item in page.json()["items"]:
            if item["message_id"] == message_id and item["status"] in terminal:
                return dict(item)
        time.sleep(0.05)
    raise AssertionError(f"{message_id} never reached a terminal status")


def test_submitting_is_accepted_before_the_answer_exists(
    client: TestClient, conversation: str
) -> None:
    """202 with IDs and a queued status, not 201 with a finished answer."""
    response = _submit(client, conversation)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["content"] == ""
    assert body["message_id"]
    assert body["run_id"]
    assert body["user_message_id"]


def test_the_stream_is_live_when_submission_returns(
    client: TestClient, conversation: str
) -> None:
    """The channel exists before the response is sent, not when a thread starts.

    Without this the client races the executor: it opens the stream, is told
    `no_active_run`, and falls back to polling for every fast run.
    """
    accepted = _submit(client, conversation)
    assert accepted.status_code == 202, accepted.text

    streamed = client.get(f"/v1/conversations/{conversation}/stream")

    assert streamed.status_code == 200
    assert "no_active_run" not in streamed.text
    assert "run.accepted" in streamed.text


def test_the_background_run_persists_its_answer(
    client: TestClient, conversation: str
) -> None:
    """The run finishes without the submitting request waiting for it."""
    accepted = _submit(client, conversation)
    message_id = accepted.json()["message_id"]

    final = _await_message(client, conversation, message_id)

    assert final["status"] == "complete"
    assert final["content"].strip()


def test_the_user_question_is_visible_immediately(
    client: TestClient, conversation: str
) -> None:
    """The question is committed with the queued run, so it is readable at once."""
    accepted = _submit(client, conversation, "Where is capture defined?")
    user_message_id = accepted.json()["user_message_id"]

    page = client.get(f"/v1/conversations/{conversation}/messages")

    posted = [
        item for item in page.json()["items"] if item["message_id"] == user_message_id
    ]
    assert posted, "the user message must be readable before the answer exists"
    assert posted[0]["content"] == "Where is capture defined?"


def test_the_stream_carries_the_run_to_completion(
    client: TestClient, conversation: str
) -> None:
    """A client that only reads the stream still learns the run finished."""
    accepted = _submit(client, conversation)
    message_id = accepted.json()["message_id"]
    _await_message(client, conversation, message_id)

    streamed = client.get(f"/v1/conversations/{conversation}/stream")

    assert streamed.status_code == 200
    names = [
        line[len("event: ") :]
        for line in streamed.text.splitlines()
        if line.startswith("event: ")
    ]
    assert "answer.completed" in names or "stream.closed" in names


def test_the_accepted_response_declares_contract_version_1_1(
    client: TestClient, conversation: str
) -> None:
    """The response shape changed, so the version must say so (ADR-0008)."""
    accepted = _submit(client, conversation)

    assert accepted.json()["contract_version"] == "1.1"


def test_replay_from_zero_is_gapless(client: TestClient, conversation: str) -> None:
    """Sequences stay monotonic and gapless across the whole run.

    No ``after``: sequences start at 0, so ``after=0`` would mean "I already
    have run.accepted" and skip it. A fresh reader wants everything.
    """
    accepted = _submit(client, conversation)
    _await_message(client, conversation, accepted.json()["message_id"])

    streamed = client.get(f"/v1/conversations/{conversation}/stream")

    sequences = [
        json.loads(line[len("data: ") :]).get("sequence")
        for line in streamed.text.splitlines()
        if line.startswith("data: ")
    ]
    observed = [value for value in sequences if isinstance(value, int)]
    if observed:
        assert observed == sorted(observed)
        assert observed == list(range(observed[0], observed[0] + len(observed)))
