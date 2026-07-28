"""Continuous freshness: running watchers and turning batches into reindexes.

This is the seam between a filesystem event and repository truth, and it is
deliberately thin. A batch of changed paths is not evidence that anything
changed — it is a reason to scan. So the batch is discarded after triggering
`IndexRepositoryService.index`, which rescans, compares content hashes, and
reuses every chunk whose content is unchanged. The paths tell us *when* to look,
never *what* to conclude (ADR-0007 decision 1).

The same is true of the periodic reconcile, which exists for the events that
were never delivered — dropped silently by an overflowed Windows watch buffer,
or produced while the process was not running. It too only triggers a scan, on
a schedule that cannot be switched off, plus an immediate catch-up requested at
startup.

Two things this owns that the watcher deliberately does not:

- **Database access.** Watchers run on their own threads, so each unit of work
  opens its own connection through the injected factory. A connection shared
  across threads corrupts, which the Phase 6 end-to-end suites demonstrated the
  hard way.
- **The per-repository switch**, which is persisted rather than held in memory:
  turning the watcher off is a decision about the repository, not the process.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.container import ApplicationServices
from codeatlas.domain.errors import IndexInProgressError, RepositoryNotFoundError
from codeatlas.indexing.debounce import (
    DEFAULT_MAX_DELAY_SECONDS,
    DEFAULT_QUIET_PERIOD_SECONDS,
    Debouncer,
)
from codeatlas.indexing.reconcile import DEFAULT_RECONCILE_INTERVAL_SECONDS
from codeatlas.indexing.watcher import RepositoryWatcher
from codeatlas.repositories.ignore_rules import IgnoreRules

ServicesFactory = Callable[[], AbstractContextManager[ApplicationServices]]


@dataclass(frozen=True)
class WatchStatus:
    """What one repository's watcher is doing, for diagnostics."""

    repository_id: str
    running: bool
    pending: bool
    failure_count: int
    last_error: str | None


class WatchService:
    """Starts, stops, and reports the per-repository watchers."""

    def __init__(
        self,
        *,
        services_factory: ServicesFactory,
        quiet_period_seconds: float = DEFAULT_QUIET_PERIOD_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        reconcile_interval_seconds: float = DEFAULT_RECONCILE_INTERVAL_SECONDS,
    ) -> None:
        if reconcile_interval_seconds <= 0:
            # ADR-0007 decision 1: the periodic scan is the only defense
            # against silently dropped events, so it is not configurable to
            # zero. Refused here rather than at watcher start, so a bad value
            # fails at construction, loudly.
            raise ValueError(
                "the reconcile interval must be positive; the periodic scan is "
                "the only defense against silently dropped filesystem events"
            )
        self._services = services_factory
        self._quiet_period_seconds = quiet_period_seconds
        self._max_delay_seconds = max_delay_seconds
        self._reconcile_interval_seconds = reconcile_interval_seconds
        self._watchers: dict[str, RepositoryWatcher] = {}
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def start_all(self) -> tuple[WatchStatus, ...]:
        """Watch every repository that has not opted out.

        Each watcher is also asked for an immediate catch-up scan: changes
        made while this process was not running produced no events, so the
        first reconcile cannot wait for the interval. The scan runs on the
        drain thread, not here, so startup is not blocked by indexing.
        """
        with self._services() as services:
            enabled = services.repositories.list_watched()
        for repository in enabled:
            watcher = self.start(
                repository.repository_id, root=Path(repository.canonical_root)
            )
            watcher.request_reconcile()
        return self.status()

    def start(
        self, repository_id: str, *, root: Path | None = None
    ) -> RepositoryWatcher:
        """Watch one repository. Idempotent; returns the live watcher."""
        with self._lock:
            existing = self._watchers.get(repository_id)
            if existing is not None:
                return existing

        resolved = root or self._root_of(repository_id)
        watcher = RepositoryWatcher(
            repository_id=repository_id,
            root=resolved,
            rules=IgnoreRules.load(resolved),
            on_batch=lambda batch: self._reindex(repository_id, batch),
            on_reconcile=lambda: self._reconcile(repository_id),
            reconcile_interval_seconds=self._reconcile_interval_seconds,
            debouncer=Debouncer(
                quiet_period_seconds=self._quiet_period_seconds,
                max_delay_seconds=self._max_delay_seconds,
            ),
        )
        with self._lock:
            # Re-check: another thread may have started one while the root was
            # being read, and two observers on one tree would double every event.
            existing = self._watchers.get(repository_id)
            if existing is not None:
                return existing
            self._watchers[repository_id] = watcher
        watcher.start()
        return watcher

    def stop(self, repository_id: str) -> None:
        """Stop watching one repository. Idempotent."""
        with self._lock:
            watcher = self._watchers.pop(repository_id, None)
        if watcher is not None:
            watcher.stop()

    def stop_all(self) -> None:
        """Stop every watcher, flushing whatever each still had pending."""
        with self._lock:
            watchers = list(self._watchers.values())
            self._watchers.clear()
        for watcher in watchers:
            watcher.stop()

    def flush(self, repository_id: str) -> None:
        """Dispatch one repository's pending batch now, without waiting."""
        with self._lock:
            watcher = self._watchers.get(repository_id)
        if watcher is not None:
            watcher.flush()

    # -- settings ----------------------------------------------------------

    def set_enabled(self, repository_id: str, *, enabled: bool) -> None:
        """Turn continuous freshness on or off, and act on it immediately."""
        with self._services() as services:
            if services.repositories.get(repository_id) is None:
                raise RepositoryNotFoundError("The repository is not registered.")
            services.repositories.set_watch_enabled(repository_id, enabled=enabled)

        if enabled:
            self.start(repository_id)
        else:
            self.stop(repository_id)

    # -- reporting ---------------------------------------------------------

    def status(self) -> tuple[WatchStatus, ...]:
        with self._lock:
            watchers = sorted(self._watchers.items())
        return tuple(
            WatchStatus(
                repository_id=repository_id,
                running=watcher.running,
                pending=watcher.pending,
                failure_count=watcher.failure_count,
                last_error=watcher.last_error,
            )
            for repository_id, watcher in watchers
        )

    # -- internals ---------------------------------------------------------

    def _root_of(self, repository_id: str) -> Path:
        with self._services() as services:
            repository = services.repositories.get(repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")
        return Path(repository.canonical_root)

    def _reindex(self, repository_id: str, batch: tuple[str, ...]) -> None:
        """Rescan the repository because ``batch`` suggests it is worth it.

        The paths are not passed down. `index` rescans and compares content
        hashes, so it reuses everything unchanged; handing it a path list would
        make it trust the event stream, which is precisely what it must not do.
        """
        try:
            with self._services() as services:
                services.indexing.index(repository_id)
        except IndexInProgressError:
            # A job is already running — possibly one this watcher started. The
            # changes are real, so they go back in the window rather than being
            # dropped; the next drain retries them. Dropping them would leave
            # the index stale with no event left to correct it.
            with self._lock:
                watcher = self._watchers.get(repository_id)
            if watcher is not None:
                watcher.requeue(batch)

    def _reconcile(self, repository_id: str) -> None:
        """Rescan the repository because the schedule says a scan is owed.

        A reconcile names no paths, so unlike a dropped batch there is nothing
        to requeue when an index is already running — the running index *is* a
        reconciling scan, establishing the same truth on this trigger's behalf.
        Any other failure propagates so the watcher counts and surfaces it.
        """
        try:
            with self._services() as services:
                services.indexing.index(repository_id)
        except IndexInProgressError:
            pass


__all__ = ["ServicesFactory", "WatchService", "WatchStatus"]
