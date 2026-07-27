"""The stream over HTTP: what a client actually receives (P5-04).

Phase 5 answers synchronously, so by the time `POST …/messages` returns, the
run has finished and its events are in the replay buffer. That is not a
weakness of the test — it is the reconnect path exercised on every run, which
is the one hardest to get right and easiest to leave untested.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.contracts import StreamEvent
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


def _events(body: str) -> list[StreamEvent]:
    parsed: list[StreamEvent] = []
    for frame in body.split("\n\n"):
        payload = next(
            (
                line[len("data: ") :]
                for line in frame.splitlines()
                if line.startswith("data: ")
            ),
            None,
        )
        if payload is None:
            continue
        decoded = json.loads(payload)
        if "sequence" in decoded:
            parsed.append(StreamEvent.model_validate(decoded))
    return parsed


def _ids(body: str) -> list[int]:
    return [
        int(line[len("id: ") :])
        for line in body.splitlines()
        if line.startswith("id: ")
    ]


def _ask(
    client: TestClient, conversation_id: str, question: str
) -> dict[str, object]:
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": question},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_a_finished_run_replays_its_whole_event_sequence(
    client: TestClient, conversation: str
) -> None:
    _ask(client, conversation, "PaymentService.capture")

    response = client.get(f"/v1/conversations/{conversation}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    kinds = [item.event.value for item in events]
    assert kinds[0] == "run.accepted"
    assert kinds[-1] == "answer.completed"
    assert "retrieval.started" in kinds
    assert "evidence.available" in kinds


def test_sequences_are_gapless_and_match_the_sse_ids(
    client: TestClient, conversation: str
) -> None:
    """`id:` is what a client sends back as `Last-Event-ID`; if it disagreed
    with the payload's sequence, resuming would skip or repeat events."""
    _ask(client, conversation, "PaymentService.capture")

    response = client.get(f"/v1/conversations/{conversation}/stream")

    events = _events(response.text)
    sequences = [item.sequence for item in events]
    assert sequences == list(range(len(sequences)))
    assert _ids(response.text) == sequences


def test_reconnecting_replays_only_what_was_missed(
    client: TestClient, conversation: str
) -> None:
    _ask(client, conversation, "PaymentService.capture")
    whole = client.get(f"/v1/conversations/{conversation}/stream")
    everything = _events(whole.text)
    assert len(everything) > 2

    resumed = client.get(
        f"/v1/conversations/{conversation}/stream",
        headers={"Last-Event-ID": str(everything[1].sequence)},
    )

    missed = _events(resumed.text)
    assert [item.sequence for item in missed] == [
        item.sequence for item in everything[2:]
    ]


def test_resuming_from_the_last_event_yields_nothing_more(
    client: TestClient, conversation: str
) -> None:
    """A client that is already current is not an error case."""
    _ask(client, conversation, "PaymentService.capture")
    whole = client.get(f"/v1/conversations/{conversation}/stream")
    last = _events(whole.text)[-1].sequence

    resumed = client.get(
        f"/v1/conversations/{conversation}/stream",
        headers={"Last-Event-ID": str(last)},
    )

    assert _events(resumed.text) == []


def test_a_malformed_resume_header_replays_from_the_beginning(
    client: TestClient, conversation: str
) -> None:
    """Stranding a client that mangled a header would be worse than replaying;
    duplicates are dropped by sequence anyway."""
    _ask(client, conversation, "PaymentService.capture")

    resumed = client.get(
        f"/v1/conversations/{conversation}/stream",
        headers={"Last-Event-ID": "not-a-number"},
    )

    assert _events(resumed.text)


def test_streaming_a_conversation_with_no_run_says_so_and_closes(
    client: TestClient, conversation: str
) -> None:
    """The client must read the persisted message rather than wait forever."""
    response = client.get(f"/v1/conversations/{conversation}/stream")

    assert response.status_code == 200
    assert "stream.closed" in response.text
    assert "fetch_final_message" in response.text


def test_streaming_an_unknown_conversation_is_not_found(
    client: TestClient,
) -> None:
    response = client.get("/v1/conversations/conv_missing/stream")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_cancelling_a_finished_run_is_refused(
    client: TestClient, conversation: str
) -> None:
    """A finished run cannot be stopped, and saying otherwise would let a UI
    paint a cancelled state over a completed answer."""
    submitted = _ask(client, conversation, "PaymentService.capture")

    response = client.post(f"/v1/message-runs/{submitted['run_id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_CANCELLABLE"
    assert response.json()["error"]["retryable"] is True


def test_cancelling_an_unknown_run_is_refused(client: TestClient) -> None:
    response = client.post("/v1/message-runs/run_missing/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_CANCELLABLE"


def test_the_stream_survives_service_rebuilding_between_requests(
    client: TestClient, conversation: str
) -> None:
    """Services are constructed per request. If the event hub were rebuilt with
    them, the request that streams a run would look in a different registry
    from the one that started it and find nothing."""
    _ask(client, conversation, "PaymentService.capture")

    first = client.get(f"/v1/conversations/{conversation}/stream")
    second = client.get(f"/v1/conversations/{conversation}/stream")

    assert _events(first.text)
    assert [item.sequence for item in _events(first.text)] == [
        item.sequence for item in _events(second.text)
    ]


def test_every_streamed_event_validates_against_the_contract(
    client: TestClient, conversation: str
) -> None:
    _ask(client, conversation, "who calls PaymentService.capture")

    response = client.get(f"/v1/conversations/{conversation}/stream")

    events = _events(response.text)
    assert events
    for event in events:
        assert event.contract_version == "1.0"
        assert event.conversation_id == conversation
        assert event.message_id
