"""The reconcile policy: when a full scan is owed, independent of events.

ADR-0007 decision 1: filesystem events are lossy, duplicated, and reordered on
every platform, and on Windows a `ReadDirectoryChangesW` buffer overflow drops
them *silently*. The periodic reconciling scan is the only defense, so it is
**not optional and not configurable to zero**.

Time is passed in, exactly as with `Debouncer`, so behavior is decided by
assertions instead of by sleeps.
"""

from __future__ import annotations

import pytest

from codeatlas.indexing.reconcile import Reconciler


def test_a_zero_interval_is_refused() -> None:
    # The ADR's words, made structural: configuring the scan to zero would
    # switch off the only defense against silently dropped events.
    with pytest.raises(ValueError, match="positive"):
        Reconciler(interval_seconds=0.0, now=1000.0)


def test_a_negative_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        Reconciler(interval_seconds=-5.0, now=1000.0)


def test_no_scan_is_owed_before_the_interval() -> None:
    reconciler = Reconciler(interval_seconds=60.0, now=1000.0)

    assert reconciler.due(now=1000.0) is False
    assert reconciler.due(now=1059.9) is False


def test_a_scan_is_owed_once_the_interval_has_elapsed() -> None:
    reconciler = Reconciler(interval_seconds=60.0, now=1000.0)

    assert reconciler.due(now=1060.0) is True


def test_recording_a_scan_restarts_the_interval() -> None:
    # Any full scan counts, however it was triggered: an event-driven reindex
    # reconciles just as a periodic one does, so the clock resets.
    reconciler = Reconciler(interval_seconds=60.0, now=1000.0)

    reconciler.record(now=1030.0)

    assert reconciler.due(now=1089.9) is False
    assert reconciler.due(now=1090.0) is True


def test_a_request_makes_the_next_check_due_immediately() -> None:
    # The startup catch-up: changes made while the process was not running
    # produced no events at all, so the first scan cannot wait for the
    # interval.
    reconciler = Reconciler(interval_seconds=60.0, now=1000.0)

    reconciler.request()

    assert reconciler.due(now=1000.1) is True


def test_a_requested_scan_then_returns_to_the_interval_schedule() -> None:
    reconciler = Reconciler(interval_seconds=60.0, now=1000.0)

    reconciler.request()
    assert reconciler.due(now=1000.1) is True
    reconciler.record(now=1000.1)

    assert reconciler.due(now=1001.0) is False
    # Clearly past the boundary: 1060.1 - 1000.1 is 59.999... in binary
    # floating point, which is a test-arithmetic artifact, not policy.
    assert reconciler.due(now=1060.2) is True
