"""Reconciliation: the scan, not the event stream, is repository truth.

Gate condition 3 of Phase 6: *filesystem events alone are never treated as
truth — a reconciling scan corrects missed, duplicated, and out-of-order
events.*

`test_watch_service.py` proved a delivered event triggers a refresh. This suite
proves the harder half: when the event stream lies — by omission, repetition,
or disorder — the reconciling scan still converges the index to what is on
disk. That is the only defense against a Windows `ReadDirectoryChangesW`
buffer overflow, which drops events *silently* (ADR-0007 decision 1).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
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
from codeatlas.storage.sqlite.stores import SnapshotStore

SERVICE_SOURCE = """class PaymentService:
    def capture(self, key: str) -> str:
        return key
"""

# Generous relative to the 0.1 s drain interval and a tiny fixture index. It is
# an upper bound on a machine under load, not an expected duration.
TIMEOUT_SECONDS = 30.0


class Harness:
    """A registered, indexed repository plus the means to query and scan it."""

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
                    request_id="req_reconcile_test",
                    repository_id=self.repository_id,
                    query=symbol,
                )
            )
        return bool(response.evidence)

    def active_snapshot_id(self) -> str:
        with connect(self.database) as connection:
            snapshot = SnapshotStore(connection).get_active(self.repository_id)
        assert snapshot is not None
        return snapshot.snapshot_id


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


REFUND_METHOD = "\n    def refund(self, key: str) -> str:\n        return key\n"


def write_refund(root: Path) -> None:
    (root / "src" / "service.py").write_text(
        SERVICE_SOURCE + REFUND_METHOD,
        encoding="utf-8",
    )


def wait_until(predicate: Callable[[], bool]) -> bool:
    """Poll until the condition holds or the bound is reached."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


class StubIndexer:
    """Stands in for `IndexRepositoryService`, counting and failing on cue."""

    def __init__(self, error: Exception) -> None:
        self.calls = 0
        self._error = error

    def index(self, repository_id_value: str) -> object:
        self.calls += 1
        raise self._error


def factory_with(harness: Harness, indexer: StubIndexer) -> object:
    """The real services, with indexing swapped for the stub."""

    @contextmanager
    def factory() -> Iterator[ApplicationServices]:
        with harness.services() as services:
            yield replace(services, indexing=cast(IndexRepositoryService, indexer))

    return factory


def test_a_change_with_no_event_is_caught_by_the_reconciling_scan(
    harness: Harness,
) -> None:
    """The missed event: the file changed and nothing told the watcher.

    This is the buffer-overflow shape. No `note` is ever called; the reconcile
    alone must converge the index to the disk.
    """
    assert not harness.resolve("PaymentService.refund")

    service = WatchService(services_factory=harness.services)
    watcher = service.start(harness.repository_id)
    try:
        write_refund(harness.root)

        watcher.request_reconcile()
        watcher.tick()

        assert harness.resolve("PaymentService.refund")
        assert watcher.failure_count == 0
    finally:
        service.stop_all()


def test_changes_made_while_the_process_was_down_are_caught_on_startup(
    harness: Harness,
) -> None:
    """The other way events are missed: there was no process to receive them.

    Starting the watchers requests an immediate catch-up scan, so a repository
    that changed while CodeAtlas was not running does not sit stale until
    something else touches it.
    """
    assert not harness.resolve("PaymentService.refund")
    write_refund(harness.root)

    service = WatchService(services_factory=harness.services)
    service.start_all()
    try:
        assert wait_until(lambda: harness.resolve("PaymentService.refund")), (
            "the startup reconcile did not catch the change made while down"
        )
    finally:
        service.stop_all()


def test_the_periodic_scan_corrects_a_missed_event_in_real_operation(
    harness: Harness,
) -> None:
    """The wiring proof: real threads, real time, no explicit reconcile.

    With a short interval this is what production does when an event never
    arrives — no `note`, no `request_reconcile`, only the clock.
    """
    assert not harness.resolve("PaymentService.refund")

    service = WatchService(
        services_factory=harness.services,
        quiet_period_seconds=0.2,
        max_delay_seconds=1.0,
        reconcile_interval_seconds=0.3,
    )
    service.start_all()
    try:
        write_refund(harness.root)

        assert wait_until(lambda: harness.resolve("PaymentService.refund")), (
            "the periodic reconcile did not correct the missed event"
        )
    finally:
        service.stop_all()


def test_duplicated_events_do_not_duplicate_the_outcome(harness: Harness) -> None:
    """The repeated event: delivery is at-least-once on every platform.

    Debounce collapses the burst, and the scan and content hashes make the
    refresh itself idempotent — the snapshot moves once, to the truth, and a
    reconcile afterward moves nothing.
    """
    service = WatchService(services_factory=harness.services)
    watcher = service.start(harness.repository_id)
    try:
        before = harness.active_snapshot_id()
        write_refund(harness.root)

        path = harness.root / "src" / "service.py"
        watcher.note(path, is_directory=False)
        watcher.note(path, is_directory=False)
        watcher.flush()

        # Resolution re-verifies the content hash against the disk, so this
        # waits for the index to reflect the final file content — not some
        # intermediate scan of a partially written file.
        assert wait_until(lambda: harness.resolve("PaymentService.refund"))
        after_edit = harness.active_snapshot_id()
        assert after_edit != before

        watcher.request_reconcile()
        watcher.tick()

        assert harness.active_snapshot_id() == after_edit
        assert watcher.failure_count == 0
    finally:
        service.stop_all()


def test_out_of_order_events_are_corrected_by_the_scan(harness: Harness) -> None:
    """The reordered event: the scan reads the disk, not the sequence.

    Events arriving in any order — including duplicates of one path between
    mentions of another — produce the index of the tree as it is, not of the
    events as they came.
    """
    service = WatchService(services_factory=harness.services)
    watcher = service.start(harness.repository_id)
    try:
        write_refund(harness.root)
        (harness.root / "src" / "audit.py").write_text(
            "def record(event: str) -> str:\n    return event\n",
            encoding="utf-8",
        )

        service_path = harness.root / "src" / "service.py"
        audit_path = harness.root / "src" / "audit.py"
        watcher.note(audit_path, is_directory=False)
        watcher.note(service_path, is_directory=False)
        watcher.note(audit_path, is_directory=False)
        watcher.flush()

        assert harness.resolve("PaymentService.refund")
        assert harness.resolve("record")
        assert watcher.failure_count == 0
    finally:
        service.stop_all()


def test_a_reconcile_during_an_index_is_not_an_error(harness: Harness) -> None:
    """An index already running *is* a reconciling scan.

    Asking for another one at the same moment is redundant, not a failure —
    and unlike a dropped batch there is nothing to requeue, because the scan
    names no paths.
    """
    busy = StubIndexer(IndexInProgressError("An indexing job is already running."))
    service = WatchService(
        services_factory=cast(ServicesFactory, factory_with(harness, busy))
    )
    watcher = service.start(harness.repository_id)
    try:
        watcher.request_reconcile()
        watcher.tick()

        assert busy.calls == 1
        assert watcher.failure_count == 0
        assert watcher.last_error is None

        # The attempt counts as the scheduled scan, so the next ticks do not
        # pile more work onto a repository that is already being indexed.
        watcher.tick()
        watcher.tick()
        assert busy.calls == 1
    finally:
        service.stop_all()


def test_a_failing_reconcile_is_visible_and_does_not_hammer(
    harness: Harness,
) -> None:
    """A reconcile failure is diagnostics, not a crash and not a retry storm.

    The watcher survives, the failure shows in status, and the next attempt
    waits for the next interval rather than firing on every 0.1 s tick.
    """
    broken = StubIndexer(OSError("the database is gone"))
    service = WatchService(
        services_factory=cast(ServicesFactory, factory_with(harness, broken))
    )
    watcher = service.start(harness.repository_id)
    try:
        watcher.request_reconcile()
        watcher.tick()
        watcher.tick()
        watcher.tick()

        entry = next(
            item
            for item in service.status()
            if item.repository_id == harness.repository_id
        )
        assert broken.calls == 1
        assert entry.failure_count == 1
        assert entry.last_error is not None
        assert "OSError" in entry.last_error
    finally:
        service.stop_all()
