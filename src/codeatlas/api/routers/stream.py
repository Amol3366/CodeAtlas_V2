"""The conversation SSE endpoint and the run-cancel route.

Hand-rolled over `StreamingResponse` rather than a dependency: the whole
protocol is `id:`, `event:`, `data:`, and a blank line, and a library for that
would be more surface than substance (ADR-0006 decision 4).

Reconnection has two paths and the choice between them is the interesting part.
Inside the replay window the client is sent exactly the events it missed.
Outside it — or after the run finished and its channel was pruned — the client
is told the stream is over and must read the persisted message. Silently
sending a partial history would let it believe it had the whole run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import StreamingResponse

from codeatlas.api.routers.repositories import Services
from codeatlas.conversations.events import format_sse, stream_events

router = APIRouter(prefix="/v1", tags=["conversations"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Proxies that buffer would defeat the point of streaming.
    "X-Accel-Buffering": "no",
}


@router.get("/conversations/{conversation_id}/stream")
async def stream_conversation(
    request: Request,
    services: Services,
    conversation_id: str,
    after: int | None = None,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> Response:
    """Stream the active run's events, resuming after the client's position.

    Resume is accepted two ways because the browser leaves no choice:
    `EventSource` cannot set request headers, so it cannot send
    `Last-Event-ID` on the initial connection. The header is the standard and
    wins when both are present; `?after=` is what a browser client can
    actually use.
    """
    # Raises CONVERSATION_NOT_FOUND for an unknown or deleted thread, before
    # any streaming response is committed.
    services.conversations.get(conversation_id)

    hub = services.conversations.hub
    channel = hub.active_for_conversation(conversation_id) if hub else None
    resume = _parse_last_event_id(last_event_id)
    if resume is None and after is not None and after >= 0:
        resume = after
    after = resume

    if channel is None:
        # No live run. Either it finished and was pruned, or none started; in
        # both cases the persisted message is the answer.
        return StreamingResponse(
            _closed_stream(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    if after is not None and not channel.buffer.can_replay_from(after):
        # The client missed events that have aged out. Saying so is the only
        # honest option: a partial replay would look complete.
        return StreamingResponse(
            _closed_stream(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    async def frames() -> AsyncIterator[str]:
        async for frame in stream_events(channel, after=after):
            if await request.is_disconnected():  # pragma: no cover - transport
                break
            yield frame

    return StreamingResponse(
        frames(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.post(
    "/message-runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED
)
def cancel_run(services: Services, run_id: str) -> Response:
    """Ask a run to stop.

    202, not 204: cancellation is cooperative, so this acknowledges the request
    rather than asserting the run has stopped. The run's own terminal event is
    what says that.
    """
    services.conversations.cancel_run(run_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


async def _closed_stream() -> AsyncIterator[str]:
    """Tell the client to read the persisted message, then close."""
    yield (
        "event: stream.closed\n"
        'data: {"reason":"no_active_run",'
        '"action":"fetch_final_message"}\n\n'
    )


def _parse_last_event_id(value: str | None) -> int | None:
    """A malformed resume header means "start from the beginning".

    Refusing would strand a client that only mangled a header; replaying from
    zero is always safe because duplicate events are dropped by sequence.
    """
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


__all__ = ["format_sse", "router"]
