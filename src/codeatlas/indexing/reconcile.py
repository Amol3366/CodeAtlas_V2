"""The periodic reconciling scan: when a full scan is owed, events or none.

The watcher reacts to events it is given. What it cannot react to is the event
that was never delivered — dropped silently when a Windows
`ReadDirectoryChangesW` buffer overflows, or produced while the process was
not running at all. The reconciling scan is the only defense, so ADR-0007
decision 1 makes it **not optional and not configurable to zero**.

A reconcile is only ever a trigger. It names no paths and concludes nothing:
the scan and the content hashes decide what changed, exactly as they do for an
event-driven refresh. Any full scan therefore counts as reconciliation,
whatever triggered it — an event-driven reindex and a periodic one establish
the same truth, so either restarts the interval.

Time is passed in rather than read, as with `Debouncer`, so behavior is
decided by assertions instead of by sleeps. The caller owns the clock; this
owns the policy.
"""

from __future__ import annotations

from typing import Final

# The backstop interval, not the freshness mechanism. Events drive ordinary
# freshness within seconds; this bounds how long a silently missed event can
# hide. A reconcile costs one scan whose unchanged files all reuse their
# chunks, so a minute is cheap insurance against the invisible failure mode.
DEFAULT_RECONCILE_INTERVAL_SECONDS: Final[float] = 60.0


class Reconciler:
    """Decides when a full scan is owed, independent of the event stream."""

    def __init__(self, *, interval_seconds: float, now: float) -> None:
        if interval_seconds <= 0:
            raise ValueError(
                "the reconcile interval must be positive; the periodic scan is "
                "the only defense against silently dropped filesystem events "
                "(ADR-0007)"
            )
        self._interval = interval_seconds
        # ``None`` means a scan has been requested outside the schedule — the
        # startup catch-up, for changes made while no process was listening.
        self._last: float | None = now

    def request(self) -> None:
        """Make the next check due immediately, regardless of the schedule."""
        self._last = None

    def due(self, *, now: float) -> bool:
        """Whether a scan is owed. A requested scan is always owed."""
        if self._last is None:
            return True
        return now - self._last >= self._interval

    def record(self, *, now: float) -> None:
        """Note that a full scan happened, however it was triggered."""
        self._last = now


__all__ = ["DEFAULT_RECONCILE_INTERVAL_SECONDS", "Reconciler"]
