"""Typed stream events, their replay window, and the runs that produce them.

`AGENTS.md` Section 11.2. Three rules drive the design:

- **Streaming text is provisional; the persisted message is authoritative.**
  Events are therefore *not* stored. Persisting them would create a second
  record of an answer that could disagree with the first, and reconciling two
  records of one answer is a problem worth never having.
- **A client resumes by sequence.** The sequence is the SSE ``id:``, so it must
  be gapless and monotonic; `Last-Event-ID` is meaningless otherwise.
- **The replay window is bounded and honest about it.** Outside the window a
  client is told to fetch the final message rather than handed a partial
  history it would mistake for the whole run.

A run outlives the request that started it: it executes on a worker thread so
the answer keeps going when a client disconnects, and so a second client (or
the same one reconnecting) can still watch it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any, Final

from codeatlas.contracts import StreamEvent, StreamEventType
from codeatlas.conversations.pipeline import CancelToken

# One run's replay window. Large enough to cover a whole ordinary run, small
# enough that a thousand idle streams cannot grow without bound.
MAX_BUFFERED_EVENTS: Final[int] = 256

# Seconds between heartbeats on an otherwise silent stream. A proxy or a
# sleeping laptop should not be able to make a live run look dead.
HEARTBEAT_SECONDS: Final[float] = 15.0

_TERMINAL_EVENTS: Final[frozenset[StreamEventType]] = frozenset(
    {
        StreamEventType.ANSWER_COMPLETED,
        StreamEventType.RUN_FAILED,
        StreamEventType.RUN_CANCELLED,
    }
)


class EventBuffer:
    """One run's events, numbered and kept for a bounded window."""

    def __init__(
        self, *, request_id: str, conversation_id: str, message_id: str
    ) -> None:
        self._request_id = request_id
        self._conversation_id = conversation_id
        self._message_id = message_id
        self._events: deque[StreamEvent] = deque(maxlen=MAX_BUFFERED_EVENTS)
        self._next_sequence = 0
        self.terminal = False

    def publish(
        self,
        event_type: StreamEventType,
        payload: dict[str, Any] | None = None,
    ) -> StreamEvent:
        event = StreamEvent(
            request_id=self._request_id,
            conversation_id=self._conversation_id,
            message_id=self._message_id,
            sequence=self._next_sequence,
            timestamp=datetime.now(UTC),
            event=event_type,
            payload=payload or {},
        )
        self._next_sequence += 1
        self._events.append(event)
        if event_type in _TERMINAL_EVENTS:
            self.terminal = True
        return event

    def replay_from(self, after: int | None) -> tuple[StreamEvent, ...]:
        """Every retained event after ``after``; all of them when ``None``."""
        if after is None:
            return tuple(self._events)
        return tuple(item for item in self._events if item.sequence > after)

    def can_replay_from(self, after: int) -> bool:
        """Whether ``after`` is still inside the retained window.

        ``False`` means the client missed events that are gone. It must fetch
        the final message instead: a partial replay would look complete.
        """
        if not self._events:
            return True
        return after >= self._events[0].sequence - 1


def format_sse(event: StreamEvent) -> str:
    """Render one event as an SSE frame.

    ``id:`` is the sequence, which is what makes `Last-Event-ID` work. The
    payload is JSON on a single line — a bare newline inside ``data:`` would
    split one event into two and desync the client's sequence tracking.
    """
    body = json.dumps(
        {
            "contract_version": event.contract_version,
            "request_id": event.request_id,
            "conversation_id": event.conversation_id,
            "message_id": event.message_id,
            "sequence": event.sequence,
            "timestamp": event.timestamp.isoformat(),
            "event": event.event.value,
            "payload": event.payload,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).replace("\n", " ")
    return f"id: {event.sequence}\nevent: {event.event.value}\ndata: {body}\n\n"


class RunChannel:
    """One in-flight run: its buffer, its subscribers, and its cancel flag."""

    def __init__(
        self,
        *,
        run_id: str,
        request_id: str,
        conversation_id: str,
        message_id: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.cancel = CancelToken()
        self.buffer = EventBuffer(
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        self._loop = loop
        self._subscribers: set[asyncio.Queue[StreamEvent | None]] = set()

    @property
    def terminal(self) -> bool:
        return self.buffer.terminal

    def publish(
        self,
        event_type: StreamEventType,
        payload: dict[str, Any] | None = None,
    ) -> StreamEvent:
        """Number an event, retain it, and wake every live subscriber.

        Safe to call from the worker thread: delivery hops back to the event
        loop, which is the only thread allowed to touch an ``asyncio.Queue``.
        """
        event = self.buffer.publish(event_type, payload)
        for queue in list(self._subscribers):
            self._deliver(queue, event)
            if self.buffer.terminal:
                self._deliver(queue, None)
        return event

    def _deliver(
        self, queue: asyncio.Queue[StreamEvent | None], item: StreamEvent | None
    ) -> None:
        if self._loop is None or self._loop.is_closed():
            queue.put_nowait(item)
            return
        # A loop torn down mid-run means nobody is listening any more; the
        # answer itself is unaffected and already committed.
        with contextlib.suppress(RuntimeError):  # pragma: no cover - teardown
            self._loop.call_soon_threadsafe(queue.put_nowait, item)

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]:
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[StreamEvent | None]) -> None:
        self._subscribers.discard(queue)


class EventHub:
    """Every run this process is currently answering, by run and by thread.

    Bounded by construction: a channel is dropped when a newer run starts for
    the same conversation, and terminal channels are pruned on each open.
    """

    def __init__(self) -> None:
        self._channels: dict[str, RunChannel] = {}
        self._active_by_conversation: dict[str, str] = {}

    def open(
        self,
        *,
        run_id: str,
        request_id: str,
        conversation_id: str,
        message_id: str,
    ) -> RunChannel:
        self._prune()
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            # Started outside an event loop (the synchronous path and most
            # tests). Delivery then happens inline, which is correct because
            # nothing is awaiting.
            loop = None
        channel = RunChannel(
            run_id=run_id,
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
            loop=loop,
        )
        self._channels[run_id] = channel
        self._active_by_conversation[conversation_id] = run_id
        return channel

    def get(self, run_id: str) -> RunChannel | None:
        return self._channels.get(run_id)

    def active_for_conversation(self, conversation_id: str) -> RunChannel | None:
        run_id = self._active_by_conversation.get(conversation_id)
        return self._channels.get(run_id) if run_id else None

    def _prune(self) -> None:
        """Forget finished runs. Their answers live in the database."""
        finished = [
            run_id
            for run_id, channel in self._channels.items()
            if channel.terminal
        ]
        for run_id in finished:
            channel = self._channels.pop(run_id)
            if self._active_by_conversation.get(channel.conversation_id) == run_id:
                self._active_by_conversation.pop(channel.conversation_id, None)


async def stream_events(
    channel: RunChannel,
    *,
    after: int | None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE frames for one run, resuming after ``after``.

    Replay comes first so a reconnecting client sees exactly what it missed,
    then live events. A silent run still emits a heartbeat, because "quiet" and
    "dead" must not look the same to a client.
    """
    queue = channel.subscribe()
    try:
        for event in channel.buffer.replay_from(after):
            yield format_sse(event)
        if channel.terminal:
            return

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield format_sse(
                    channel.buffer.publish(StreamEventType.HEARTBEAT)
                )
                continue
            if item is None:
                return
            yield format_sse(item)
    finally:
        channel.unsubscribe(queue)


def replay_frames(channel: RunChannel, after: int | None) -> Iterator[str]:
    """Synchronous replay, for a run that has already finished."""
    for event in channel.buffer.replay_from(after):
        yield format_sse(event)


__all__ = [
    "HEARTBEAT_SECONDS",
    "MAX_BUFFERED_EVENTS",
    "EventBuffer",
    "EventHub",
    "RunChannel",
    "format_sse",
    "replay_frames",
    "stream_events",
]
