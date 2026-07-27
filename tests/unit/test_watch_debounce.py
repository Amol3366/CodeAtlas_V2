"""Debounce logic for filesystem events.

Kept free of threads and real time so the behavior is decided by assertions
rather than by sleeps. A test that waits is a test that is slow when it passes
and flaky when it fails.

The two bounds exist for different reasons and both are tested here: the quiet
period coalesces a burst, and the maximum delay stops a continuously-changing
tree from postponing the batch forever.
"""

from __future__ import annotations

import pytest

from codeatlas.indexing.debounce import Debouncer

QUIET = 0.5
MAX_DELAY = 3.0


@pytest.fixture()
def debouncer() -> Debouncer:
    return Debouncer(quiet_period_seconds=QUIET, max_delay_seconds=MAX_DELAY)


def test_nothing_is_due_without_events(debouncer: Debouncer) -> None:
    assert debouncer.due(now=100.0) is None


def test_a_single_event_waits_for_the_quiet_period(debouncer: Debouncer) -> None:
    debouncer.record("src/a.py", now=100.0)

    assert debouncer.due(now=100.0 + QUIET / 2) is None
    assert debouncer.due(now=100.0 + QUIET) == ("src/a.py",)


def test_a_burst_becomes_one_batch(debouncer: Debouncer) -> None:
    # Saving a file in an editor, or a branch switch, produces many events for
    # one logical change. Reindexing once per event would be pure waste.
    for offset, path in enumerate(["src/a.py", "src/b.py", "src/c.py"]):
        debouncer.record(path, now=100.0 + offset * 0.1)

    assert debouncer.due(now=100.2 + QUIET / 2) is None
    assert debouncer.due(now=100.2 + QUIET) == ("src/a.py", "src/b.py", "src/c.py")


def test_each_event_extends_the_quiet_period(debouncer: Debouncer) -> None:
    debouncer.record("src/a.py", now=100.0)
    assert debouncer.due(now=100.4) is None

    debouncer.record("src/b.py", now=100.4)
    # The original event is now well past its own quiet period, but the batch
    # is not: activity is still arriving.
    assert debouncer.due(now=100.6) is None
    assert debouncer.due(now=100.9) == ("src/a.py", "src/b.py")


def test_continuous_activity_still_flushes_at_the_maximum_delay(
    debouncer: Debouncer,
) -> None:
    # A build writing into the tree, or a long checkout, can emit events faster
    # than the quiet period forever. Without this bound the index would never
    # refresh while anything was happening — the worst possible time to stall.
    now = 100.0
    while now < 100.0 + MAX_DELAY:
        debouncer.record("src/a.py", now=now)
        assert debouncer.due(now=now) is None
        now += QUIET / 2

    debouncer.record("src/b.py", now=now)
    assert debouncer.due(now=now) == ("src/a.py", "src/b.py")


def test_a_batch_is_delivered_once(debouncer: Debouncer) -> None:
    debouncer.record("src/a.py", now=100.0)

    assert debouncer.due(now=101.0) == ("src/a.py",)
    assert debouncer.due(now=102.0) is None


def test_repeated_paths_collapse(debouncer: Debouncer) -> None:
    # Editors write, truncate, and rename; one save is several events on one
    # path. The batch names paths to look at, so duplicates say nothing extra.
    for offset in range(5):
        debouncer.record("src/a.py", now=100.0 + offset * 0.01)

    assert debouncer.due(now=101.0) == ("src/a.py",)


def test_paths_are_ordered_so_batches_are_reproducible(debouncer: Debouncer) -> None:
    for path in ["src/z.py", "src/a.py", "src/m.py"]:
        debouncer.record(path, now=100.0)

    assert debouncer.due(now=101.0) == ("src/a.py", "src/m.py", "src/z.py")


def test_pending_reports_whether_work_is_waiting(debouncer: Debouncer) -> None:
    assert not debouncer.pending

    debouncer.record("src/a.py", now=100.0)
    assert debouncer.pending

    debouncer.due(now=101.0)
    assert not debouncer.pending


@pytest.mark.parametrize(
    ("quiet", "maximum"),
    [(0.0, 1.0), (-1.0, 1.0), (0.5, 0.0), (1.0, 0.5)],
)
def test_nonsensical_windows_are_refused(quiet: float, maximum: float) -> None:
    # A zero quiet period is not debouncing, and a maximum below the quiet
    # period would flush mid-burst on every batch. Both are configuration
    # mistakes worth failing loudly rather than absorbing.
    with pytest.raises(ValueError):
        Debouncer(quiet_period_seconds=quiet, max_delay_seconds=maximum)
