"""Coalescing filesystem events into batches worth acting on.

One logical change is many filesystem events. Saving a file in an editor writes,
truncates, and renames; a branch switch touches thousands of paths; a build
writes into the tree continuously. Reindexing per event would spend most of its
time redoing work that the next event invalidates.

Two bounds, for two different failure modes:

- **The quiet period** waits for a burst to finish. It is what turns a save into
  one refresh instead of four.
- **The maximum delay** caps how long that waiting can go on. Without it, a tree
  that changes faster than the quiet period would postpone the batch forever —
  and it would do so exactly while the index was going stale fastest, which is
  the worst possible moment to stall.

Time is passed in rather than read, so behavior is decided by assertions instead
of by sleeps. The caller owns the clock; this owns the policy.
"""

from __future__ import annotations

from typing import Final

# Defaults chosen for an interactive editor rather than a batch job: long
# enough that one save is one refresh, short enough that a developer does not
# notice waiting for it.
DEFAULT_QUIET_PERIOD_SECONDS: Final[float] = 0.75
DEFAULT_MAX_DELAY_SECONDS: Final[float] = 5.0


class Debouncer:
    """Collects changed paths and releases them as one batch.

    Not thread-safe by itself; the watcher owns a lock around it, because
    filesystem events arrive on the observer's thread and batches are consumed
    on another.
    """

    def __init__(
        self,
        *,
        quiet_period_seconds: float = DEFAULT_QUIET_PERIOD_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    ) -> None:
        if quiet_period_seconds <= 0:
            raise ValueError("the quiet period must be positive")
        if max_delay_seconds < quiet_period_seconds:
            raise ValueError(
                "the maximum delay must be at least the quiet period; "
                "a smaller value would flush every batch mid-burst"
            )
        self._quiet_period = quiet_period_seconds
        self._max_delay = max_delay_seconds
        self._paths: set[str] = set()
        self._first_recorded_at: float | None = None
        self._last_recorded_at: float = 0.0

    @property
    def pending(self) -> bool:
        """Whether any path is waiting to be released."""
        return bool(self._paths)

    def record(self, relative_path: str, *, now: float) -> None:
        """Note that a path changed. Repeats collapse."""
        if self._first_recorded_at is None:
            self._first_recorded_at = now
        self._last_recorded_at = now
        self._paths.add(relative_path)

    def due(self, *, now: float) -> tuple[str, ...] | None:
        """Release the batch if either bound has been reached.

        Returns ``None`` while the batch is still gathering, so a caller can
        poll without having to know the policy.
        """
        if self._first_recorded_at is None:
            return None

        quiet_enough = now - self._last_recorded_at >= self._quiet_period
        waited_long_enough = now - self._first_recorded_at >= self._max_delay
        if not (quiet_enough or waited_long_enough):
            return None

        return self.flush()

    def flush(self) -> tuple[str, ...] | None:
        """Release whatever is pending, ignoring both bounds.

        Used when waiting is no longer the right thing: shutting down, or
        retrying a batch that could not be indexed. Paths noted just before a
        stop are real changes, and discarding them would leave the index stale
        with nothing left to report it.
        """
        if not self._paths:
            return None
        # Sorted so a batch is reproducible: the same changes produce the same
        # batch regardless of the order the operating system reported them.
        batch = tuple(sorted(self._paths))
        self._paths.clear()
        self._first_recorded_at = None
        return batch


__all__ = [
    "DEFAULT_MAX_DELAY_SECONDS",
    "DEFAULT_QUIET_PERIOD_SECONDS",
    "Debouncer",
]
