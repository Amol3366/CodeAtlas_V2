"""Running an accepted turn off the request thread (P6-STREAM, ADR-0008).

Phase 5 executed the run inside the submitting request, so the response could
not be sent until the answer existed. That made three things impossible rather
than merely awkward: a long run held an HTTP request open for its full
duration, `cancel` could only ever arrive after the run it named had finished,
and no run was ever in flight for a stream to attach to.

This module is the seam that fixes it, and it is deliberately small.

**A queued run is described by values, never by objects.** `QueuedRun` holds
only strings and an integer. The background thread must not touch the
submitting request's `ConversationService`, `Connection`, or any row object
loaded on it — a SQLite connection shared across threads corrupts, which the
P6-01 end-to-end suites demonstrated by producing one request's result columns
in another request's response. So the job carries the facts and the worker
rebuilds everything else from its own connection.

**The event channel is *not* opened here.** It is opened by the submitting
request before it responds, because a client that submits and immediately
opens the stream would otherwise race the executor and be told there is no
active run. Opening it on the request thread is what makes the accepted
response a promise the stream can keep.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeatlas.application.container import ApplicationServices

ServicesFactory = Callable[[], AbstractContextManager["ApplicationServices"]]

DEFAULT_MAX_WORKERS = 4
"""Bounded on purpose: an unbounded pool turns a burst of questions into a
burst of full retrievals, and the answer nobody is waiting for still costs the
same CPU as the one they are."""


@dataclass(frozen=True)
class QueuedRun:
    """Everything a worker needs to answer one accepted turn.

    Values only. See the module docstring for why this may not carry objects.
    """

    run_id: str
    conversation_id: str
    message_id: str
    user_message_id: str
    question: str
    sequence: int
    request_id: str
    intent: str


class RunExecutor(Protocol):
    """Where an accepted run is carried out."""

    def schedule(self, queued: QueuedRun) -> None:
        """Take ownership of the run. Must not raise for a healthy queue."""

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop accepting work and release the workers."""


class ThreadedRunExecutor:
    """Runs accepted turns on a bounded pool, each with its own services."""

    def __init__(
        self,
        services_factory: ServicesFactory,
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self._services_factory = services_factory
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="codeatlas-run"
        )

    def schedule(self, queued: QueuedRun) -> None:
        self._pool.submit(self._run, queued)

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)

    def _run(self, queued: QueuedRun) -> None:
        """Answer one turn on a worker thread.

        Nothing is re-raised. There is no caller left to receive an exception —
        the submitting request returned long ago — and the run's outcome is
        already recorded in the database and published to the channel by
        `execute_queued_run` itself. Letting an exception escape would only
        reach the pool's future, which nobody reads, and would leave the turn
        looking queued forever.
        """
        with self._services_factory() as services:
            services.conversations.execute_queued_run(queued)


__all__ = [
    "DEFAULT_MAX_WORKERS",
    "QueuedRun",
    "RunExecutor",
    "ServicesFactory",
    "ThreadedRunExecutor",
]
