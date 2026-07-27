"""Continuous freshness: a change on disk reaches query results unasked.

Gate condition 2 of Phase 6. The suite drives the watcher's `note`/`tick`
directly rather than sleeping on real filesystem events — the event *shell* is
covered separately in `test_watcher_end_to_end.py`. Separating them keeps the
behavioral assertions fast and deterministic while still proving the wiring.

Throughout, the thing being verified is that the watcher only ever *triggers*
work. The scan and the content hashes decide what actually changed, so an event
for an untouched file costs a scan and nothing else.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.indexing import IndexRepositoryService
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.watching import ServicesFactory, WatchService
from codeatlas.domain.errors import IndexInProgressError
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SERVICE_SOURCE = """class PaymentService:
    def capture(self, key: str) -> str:
        return key
"""


class Harness:
    """A registered, indexed repository plus a watch service over it."""

    def __init__(self, root: Path, database: Path, repository_id: str) -> None:
        self.root = root
        self.database = database
        self.repository_id = repository_id

    @contextmanager
    def services(self) -> Iterator[ApplicationServices]:
        # One connection per unit of work, never one shared across threads:
        # the watcher runs on its own thread and a shared connection corrupts.
        with connect(self.database) as connection:
            yield build_services(connection)

    def resolve(self, symbol: str) -> bool:
        with self.services() as services:
            response = services.lookup.lookup(
                SymbolLookupRequest(
                    request_id="req_watch_test",
                    repository_id=self.repository_id,
                    query=symbol,
                )
            )
        return bool(response.evidence)


@pytest.fixture()
def harness(tmp_path: Path) -> Harness:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "service.py").write_text(SERVICE_SOURCE, encoding="utf-8")

    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root), display_name="watched")
        )
        services.indexing.index(repository.repository_id)
    return Harness(root, database, repository.repository_id)


def watch_service(harness: Harness) -> WatchService:
    return WatchService(services_factory=harness.services)


def test_a_new_symbol_becomes_answerable_without_an_index_command(
    harness: Harness,
) -> None:
    """The whole point of the phase, in one assertion."""
    assert not harness.resolve("PaymentService.refund")

    service = watch_service(harness)
    watcher = service.start(harness.repository_id)

    (harness.root / "src" / "service.py").write_text(
        SERVICE_SOURCE
        + "\n    def refund(self, key: str) -> str:\n        return key\n",
        encoding="utf-8",
    )
    watcher.note(harness.root / "src" / "service.py", is_directory=False)
    service.flush(harness.repository_id)

    assert harness.resolve("PaymentService.refund")
    service.stop_all()


def test_a_disabled_repository_is_not_watched(harness: Harness) -> None:
    service = watch_service(harness)
    service.set_enabled(harness.repository_id, enabled=False)

    service.start_all()

    assert service.status() == ()
    service.stop_all()


def test_enabling_starts_a_watcher_and_disabling_stops_it(harness: Harness) -> None:
    service = watch_service(harness)

    service.set_enabled(harness.repository_id, enabled=False)
    service.start_all()
    assert service.status() == ()

    service.set_enabled(harness.repository_id, enabled=True)
    assert [entry.repository_id for entry in service.status()] == [
        harness.repository_id
    ]

    service.set_enabled(harness.repository_id, enabled=False)
    assert service.status() == ()
    service.stop_all()


def test_the_switch_survives_a_restart(harness: Harness) -> None:
    # Turning the watcher off is a decision about this repository, not about
    # this process. Losing it on restart would silently re-enable watching on a
    # network share the user deliberately excluded.
    watch_service(harness).set_enabled(harness.repository_id, enabled=False)

    fresh = watch_service(harness)
    fresh.start_all()

    assert fresh.status() == ()
    fresh.stop_all()


def test_start_all_watches_every_enabled_repository(harness: Harness) -> None:
    service = watch_service(harness)
    service.start_all()

    running = service.status()
    assert [entry.repository_id for entry in running] == [harness.repository_id]
    assert running[0].running is True
    service.stop_all()


class StubIndexer:
    """Stands in for `IndexRepositoryService`, counting and failing on cue."""

    def __init__(self, error: Exception | None, *, fail_times: int) -> None:
        self.calls = 0
        self._error = error
        self._fail_times = fail_times

    def index(self, repository_id_value: str) -> object:
        self.calls += 1
        if self._error is not None and self.calls <= self._fail_times:
            raise self._error
        return None


def factory_with(harness: Harness, indexer: StubIndexer) -> object:
    """The real services, with indexing swapped for the stub."""

    @contextmanager
    def factory() -> Iterator[ApplicationServices]:
        with harness.services() as services:
            yield replace(services, indexing=cast(IndexRepositoryService, indexer))

    return factory


def test_a_concurrent_index_defers_the_batch_rather_than_dropping_it(
    harness: Harness,
) -> None:
    """A change that arrives mid-index must not be forgotten.

    Dropping it would leave the index stale with no event left to correct it —
    silent staleness produced by the very component meant to prevent it.
    """
    busy = StubIndexer(
        IndexInProgressError("An indexing job is already running."), fail_times=1
    )
    service = WatchService(
        services_factory=cast(ServicesFactory, factory_with(harness, busy))
    )
    watcher = service.start(harness.repository_id)

    watcher.note(harness.root / "src" / "service.py", is_directory=False)
    service.flush(harness.repository_id)
    assert busy.calls == 1

    # The deferred paths were put back, so the next drain retries them rather
    # than the change waiting for an unrelated future event.
    service.flush(harness.repository_id)
    assert busy.calls == 2
    service.stop_all()


def test_status_reports_a_persistent_failure(harness: Harness) -> None:
    broken = StubIndexer(OSError("the database is gone"), fail_times=10)
    service = WatchService(
        services_factory=cast(ServicesFactory, factory_with(harness, broken))
    )
    watcher = service.start(harness.repository_id)

    watcher.note(harness.root / "src" / "service.py", is_directory=False)
    service.flush(harness.repository_id)

    entry = service.status()[0]
    assert entry.failure_count == 1
    assert entry.last_error is not None
    assert "OSError" in entry.last_error
    service.stop_all()


def test_stopping_does_not_discard_pending_work(harness: Harness) -> None:
    # Paths noted just before shutdown are real changes. Dropping them would
    # leave the index stale with nothing left to say so.
    indexer = StubIndexer(None, fail_times=0)
    service = WatchService(
        services_factory=cast(ServicesFactory, factory_with(harness, indexer))
    )
    watcher = service.start(harness.repository_id)

    watcher.note(harness.root / "src" / "service.py", is_directory=False)
    service.stop_all()

    assert indexer.calls == 1
