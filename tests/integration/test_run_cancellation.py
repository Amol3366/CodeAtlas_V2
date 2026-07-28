"""Cancelling a run that is actually in flight (P6-STREAM, ADR-0008).

Before P6-STREAM this could not be tested, and worse, could not happen: the
submission executed its run inline, so `cancel_run` could only ever arrive
after the run it named had already finished. The endpoint existed and could
never do what its name said.

These tests hold a run open on a worker thread with a pipeline that blocks
until told otherwise, so cancellation lands in the middle of a real run rather
than being simulated.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.application.conversation_service import ConversationService
from codeatlas.contracts import MessageStatus
from codeatlas.conversations.events import EventHub
from codeatlas.conversations.executor import ThreadedRunExecutor
from codeatlas.conversations.pipeline import CancelledError, CancelToken
from codeatlas.domain.errors import RunNotCancellableError
from codeatlas.domain.repository import Repository
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ConversationStore, RepositoryStore

_STARTED = threading.Event()
_RELEASE = threading.Event()


class _BlockingPipeline:
    """Stops inside the run and honours cancellation, like the real one.

    The real pipeline checks its token between retrieval stages. This narrows
    that to a single checkpoint so a test can stand exactly on it.
    """

    def execute(
        self, request: object, *, on_event: object = None, cancel: CancelToken | None
    ) -> object:
        _STARTED.set()
        # Wait for the test, but wake often enough to notice cancellation.
        while not _RELEASE.wait(timeout=0.02):
            if cancel is not None and cancel.cancelled:
                raise CancelledError
        if cancel is not None and cancel.cancelled:
            raise CancelledError
        raise AssertionError("the test must cancel or release this run")


@pytest.fixture(autouse=True)
def _reset_signals() -> Iterator[None]:
    _STARTED.clear()
    _RELEASE.clear()
    yield
    _RELEASE.set()


@pytest.fixture()
def service(tmp_path: Path, sample_repo: Path) -> Iterator[ConversationService]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as setup:
        apply_migrations(setup)

    hub = EventHub()

    def open_connection() -> sqlite3.Connection:
        connection = sqlite3.connect(database_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def build(connection: sqlite3.Connection) -> ConversationService:
        return ConversationService(
            repositories=RepositoryStore(connection),
            conversations=ConversationStore(connection),
            connection=connection,
            pipeline=_BlockingPipeline(),  # type: ignore[arg-type]
            hub=hub,
        )

    @contextmanager
    def factory() -> Iterator[object]:
        # Each worker gets its own connection — the P6-01 rule, applied here
        # rather than restated.
        connection = open_connection()
        try:

            class _Services:
                conversations = build(connection)

            yield _Services()
        finally:
            connection.close()

    executor = ThreadedRunExecutor(factory)  # type: ignore[arg-type]
    connection = open_connection()
    repositories = RepositoryStore(connection)
    repositories.add(
        Repository(
            repository_id="repo_cancel",
            display_name=sample_repo.name,
            canonical_root=str(sample_repo),
            created_at=datetime.now(UTC),
        )
    )
    submitting = ConversationService(
        repositories=repositories,
        conversations=ConversationStore(connection),
        connection=connection,
        pipeline=_BlockingPipeline(),  # type: ignore[arg-type]
        hub=hub,
        executor=executor,
    )
    try:
        yield submitting
    finally:
        _RELEASE.set()
        executor.shutdown(wait=True)
        connection.close()


def test_a_run_in_flight_can_be_cancelled(service: ConversationService) -> None:
    """The endpoint reaches a run that is genuinely executing."""
    conversation = service.create("repo_cancel")
    accepted = service.submit(conversation.conversation_id, "PaymentService.capture")
    assert accepted.status is MessageStatus.QUEUED
    assert _STARTED.wait(timeout=10.0), "the run never started on a worker"

    service.cancel_run(accepted.run_id)

    deadline = threading.Event()
    for _ in range(500):
        message = service.list_messages(conversation.conversation_id).items
        current = [m for m in message if m.message_id == accepted.message_id]
        if current and current[0].status is MessageStatus.CANCELLED:
            break
        deadline.wait(0.02)
    else:  # pragma: no cover - only on failure
        raise AssertionError("the cancelled run never reached CANCELLED")


def test_cancelling_an_unknown_run_is_refused(service: ConversationService) -> None:
    """A run nobody is executing cannot be cancelled, and says so."""
    with pytest.raises(RunNotCancellableError):
        service.cancel_run("run_does_not_exist")
