"""The watcher's reconcile wiring, driven by a fake clock.

The policy itself is proven in `test_reconciler.py`; these tests prove the
watcher acts on it: a reconcile fires when it is due and only then, an
event-driven reindex counts as a scan, a failure is visible and does not turn
into a hammer, and `request_reconcile` covers the startup case.

The rule under test throughout is still ADR-0007 decision 1: the watcher only
ever *triggers* work — a reconcile names no paths at all, because the scan and
the content hashes decide what changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.indexing.debounce import Debouncer
from codeatlas.indexing.watcher import (
    BatchCallback,
    ReconcileCallback,
    RepositoryWatcher,
)
from codeatlas.repositories.ignore_rules import IgnoreRules

INTERVAL = 30.0


class FakeClock:
    """A clock the test advances explicitly."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


def build(
    root: Path,
    clock: FakeClock,
    *,
    on_batch: BatchCallback | None = None,
    on_reconcile: ReconcileCallback | None = None,
) -> RepositoryWatcher:
    return RepositoryWatcher(
        repository_id="repo_1",
        root=root,
        rules=IgnoreRules.load(root),
        on_batch=on_batch or (lambda batch: None),
        on_reconcile=on_reconcile,
        reconcile_interval_seconds=INTERVAL,
        debouncer=Debouncer(quiet_period_seconds=0.5, max_delay_seconds=3.0),
        clock=clock,
    )


def test_no_reconcile_fires_before_the_interval(root: Path, clock: FakeClock) -> None:
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    clock.advance(INTERVAL - 1.0)
    watcher.tick()

    assert reconciles == []


def test_a_reconcile_fires_once_the_interval_elapses(
    root: Path, clock: FakeClock
) -> None:
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    clock.advance(INTERVAL)
    watcher.tick()

    assert reconciles == ["scan"]


def test_a_reconcile_fires_once_per_interval_not_once_per_tick(
    root: Path, clock: FakeClock
) -> None:
    # The drain thread ticks far more often than the interval. A reconcile
    # that fired per tick would rescan the repository ten times a second.
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    clock.advance(INTERVAL)
    watcher.tick()
    watcher.tick()
    watcher.tick()

    assert reconciles == ["scan"]

    clock.advance(INTERVAL)
    watcher.tick()

    assert reconciles == ["scan", "scan"]


def test_a_reconcile_names_no_paths(root: Path, clock: FakeClock) -> None:
    # A batch names candidates; a reconcile names nothing, because nothing
    # about the event stream is trusted to say what changed. The scan decides.
    # A zero-argument callable would raise `TypeError` if it were ever called
    # with a path list, so surviving the tick is the assertion.
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    clock.advance(INTERVAL)
    watcher.tick()

    assert reconciles == ["scan"]


def test_a_successful_event_driven_reindex_counts_as_a_scan(
    root: Path, clock: FakeClock
) -> None:
    # An index triggered by a batch is a full scan. Reconciling again moments
    # later would rescan to learn nothing, so the interval restarts.
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    clock.advance(INTERVAL - 10.0)
    watcher.note(root / "src" / "a.py", is_directory=False)
    watcher.flush()  # the batch's reindex runs now, at INTERVAL - 10

    clock.advance(INTERVAL - 1.0)  # INTERVAL - 1 since the scan < INTERVAL
    watcher.tick()
    assert reconciles == []

    clock.advance(1.0)  # now a full INTERVAL since the scan
    watcher.tick()
    assert reconciles == ["scan"]


def test_a_failed_batch_does_not_count_as_a_scan(root: Path, clock: FakeClock) -> None:
    # The requeue path retries the batch; the reconcile schedule must reflect
    # that no scan actually happened.
    reconciles: list[str] = []

    def explode(batch: tuple[str, ...]) -> None:
        raise OSError("disk full")

    watcher = build(
        root, clock, on_batch=explode, on_reconcile=lambda: reconciles.append("scan")
    )

    clock.advance(INTERVAL - 10.0)
    watcher.note(root / "src" / "a.py", is_directory=False)
    watcher.flush()

    clock.advance(10.0)
    watcher.tick()

    assert reconciles == ["scan"]


def test_a_failing_reconcile_is_counted_and_not_retried_until_the_next_interval(
    root: Path, clock: FakeClock
) -> None:
    # Retrying every tick would hammer a repository whose index keeps failing.
    # The attempt is recorded, the failure is visible, and the next try waits
    # for the next interval.
    calls = 0

    def broken() -> None:
        nonlocal calls
        calls += 1
        raise OSError("the database is gone")

    watcher = build(root, clock, on_reconcile=broken)

    clock.advance(INTERVAL)
    watcher.tick()
    assert calls == 1
    assert watcher.failure_count == 1
    assert watcher.last_error is not None
    assert "OSError" in watcher.last_error

    watcher.tick()
    watcher.tick()
    assert calls == 1

    clock.advance(INTERVAL)
    watcher.tick()
    assert calls == 2


def test_request_reconcile_scans_on_the_next_tick(
    root: Path, clock: FakeClock
) -> None:
    # The startup case: changes made while the process was not running
    # produced no events, so the catch-up cannot wait for the interval.
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    watcher.request_reconcile()
    watcher.tick()

    assert reconciles == ["scan"]


def test_a_requested_reconcile_returns_to_the_schedule_afterward(
    root: Path, clock: FakeClock
) -> None:
    reconciles: list[str] = []
    watcher = build(root, clock, on_reconcile=lambda: reconciles.append("scan"))

    watcher.request_reconcile()
    watcher.tick()
    watcher.tick()

    clock.advance(INTERVAL)
    watcher.tick()

    assert reconciles == ["scan", "scan"]


def test_a_watcher_without_a_reconcile_callback_never_scans(
    root: Path, clock: FakeClock
) -> None:
    # The standalone default is unchanged: no callback, no reconcile. The
    # product-level "always reconciles" rule is owned by `WatchService`.
    watcher = build(root, clock)

    watcher.request_reconcile()  # a no-op, not an error
    clock.advance(INTERVAL * 10)
    watcher.tick()

    assert watcher.failure_count == 0
