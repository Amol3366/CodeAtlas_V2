"""The typed stream event contract (P5-04, `AGENTS.md` Section 11.2).

These tests are about the envelope and the buffer, not about HTTP. A client
resumes from a sequence number and ignores what it does not recognize, so the
sequence discipline and the replay window are the load-bearing parts.
"""

from __future__ import annotations

import pytest

from codeatlas.contracts import StreamEvent, StreamEventType
from codeatlas.conversations.events import MAX_BUFFERED_EVENTS, EventBuffer


def _buffer() -> EventBuffer:
    return EventBuffer(
        request_id="req_1", conversation_id="conv_1", message_id="msg_2"
    )


def test_sequences_start_at_zero_and_increase_by_one() -> None:
    """The sequence is the resume key: a gap or a repeat would make
    `Last-Event-ID` ambiguous."""
    buffer = _buffer()

    first = buffer.publish(StreamEventType.RUN_ACCEPTED)
    second = buffer.publish(StreamEventType.RETRIEVAL_STARTED)
    third = buffer.publish(StreamEventType.ANSWER_COMPLETED)

    assert [first.sequence, second.sequence, third.sequence] == [0, 1, 2]


def test_every_event_carries_the_full_envelope() -> None:
    buffer = _buffer()

    event = buffer.publish(
        StreamEventType.RETRIEVAL_PROGRESS, {"channel": "graph"}
    )

    assert isinstance(event, StreamEvent)
    assert event.contract_version == "1.1"
    assert event.request_id == "req_1"
    assert event.conversation_id == "conv_1"
    assert event.message_id == "msg_2"
    assert event.timestamp.utcoffset() is not None
    assert event.payload == {"channel": "graph"}


def test_replay_returns_only_events_after_the_given_sequence() -> None:
    buffer = _buffer()
    buffer.publish(StreamEventType.RUN_ACCEPTED)
    buffer.publish(StreamEventType.RETRIEVAL_STARTED)
    buffer.publish(StreamEventType.ANSWER_COMPLETED)

    assert [item.sequence for item in buffer.replay_from(None)] == [0, 1, 2]
    assert [item.sequence for item in buffer.replay_from(0)] == [1, 2]
    assert [item.sequence for item in buffer.replay_from(2)] == []


def test_replay_beyond_the_end_is_empty_rather_than_an_error() -> None:
    """A client that resumes from a sequence it already has is not wrong; it
    has simply seen everything."""
    buffer = _buffer()
    buffer.publish(StreamEventType.RUN_ACCEPTED)

    assert buffer.replay_from(99) == ()


def test_the_buffer_is_bounded_and_says_when_it_has_dropped_events() -> None:
    """Outside the window the client must fetch the final message instead of
    replaying: silently sending a partial history would let it believe it had
    the whole run."""
    buffer = _buffer()
    for _ in range(MAX_BUFFERED_EVENTS + 10):
        buffer.publish(StreamEventType.RETRIEVAL_PROGRESS)

    assert len(buffer.replay_from(None)) == MAX_BUFFERED_EVENTS
    assert buffer.can_replay_from(0) is False
    assert buffer.can_replay_from(MAX_BUFFERED_EVENTS + 5) is True


def test_a_terminal_event_closes_the_buffer() -> None:
    buffer = _buffer()
    assert buffer.terminal is False

    buffer.publish(StreamEventType.RETRIEVAL_STARTED)
    assert buffer.terminal is False

    buffer.publish(StreamEventType.ANSWER_COMPLETED)
    assert buffer.terminal is True


@pytest.mark.parametrize(
    "event_type",
    [
        StreamEventType.ANSWER_COMPLETED,
        StreamEventType.RUN_FAILED,
        StreamEventType.RUN_CANCELLED,
    ],
)
def test_every_terminal_kind_closes_the_buffer(
    event_type: StreamEventType,
) -> None:
    """A failed or cancelled run ends the stream exactly as a completed one
    does; a client waiting for `answer.completed` alone would hang forever."""
    buffer = _buffer()
    buffer.publish(event_type)
    assert buffer.terminal is True


def test_a_heartbeat_does_not_end_the_stream() -> None:
    buffer = _buffer()
    buffer.publish(StreamEventType.HEARTBEAT)
    assert buffer.terminal is False


def test_events_serialize_with_their_sequence_as_the_sse_id() -> None:
    """`id:` is the sequence, which is what makes `Last-Event-ID` work."""
    from codeatlas.conversations.events import format_sse

    buffer = _buffer()
    event = buffer.publish(StreamEventType.RUN_ACCEPTED, {"run_id": "run_1"})

    rendered = format_sse(event)

    assert rendered.startswith("id: 0\n")
    assert "event: run.accepted\n" in rendered
    assert rendered.endswith("\n\n")
    assert '"run_id":"run_1"' in rendered.replace(" ", "")


def test_serialized_events_never_contain_a_bare_newline_in_data() -> None:
    """A newline inside `data:` would split one event into two and desync the
    client's sequence tracking."""
    from codeatlas.conversations.events import format_sse

    buffer = _buffer()
    event = buffer.publish(
        StreamEventType.RUN_WARNING, {"message": "line one\nline two"}
    )

    body = [
        line for line in format_sse(event).splitlines() if line.startswith("data:")
    ]
    assert len(body) == 1
