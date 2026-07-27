"""Watching one repository root and reporting debounced batches of candidates.

ADR-0007 decision 1: **the watcher is a trigger, never an authority.** An event
says "look here". A scan and a content hash decide what actually changed. This
module therefore never concludes anything about a file — it decides only which
paths are worth looking at, and says so once per burst.

That distinction is not pedantry. Filesystem event delivery is lossy,
duplicated, and reordered on every platform, and on Windows a
`ReadDirectoryChangesW` buffer overflow drops events *silently* — the API
reports success while telling you nothing happened. Anything that treated these
events as truth would produce exactly the silent staleness Phase 6 exists to
prevent. The periodic reconciling scan (P6-03) is what covers the gap.

The policy lives in `note` and `tick`, which are ordinary methods with no
threads or clocks of their own. `start`/`stop` are a thin shell that feeds them
from a watchdog observer.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from codeatlas.indexing.debounce import Debouncer
from codeatlas.repositories.ignore_rules import IgnoreRules

# How often the drain thread looks for a due batch. Well below the quiet period,
# so the delay a user perceives is the debounce policy rather than this.
DEFAULT_POLL_INTERVAL_SECONDS: Final[float] = 0.1

BatchCallback = Callable[[tuple[str, ...]], None]


class RepositoryWatcher:
    """Watches one repository root and reports batches of changed paths."""

    def __init__(
        self,
        *,
        repository_id: str,
        root: Path,
        rules: IgnoreRules,
        on_batch: BatchCallback,
        debouncer: Debouncer | None = None,
        clock: Callable[[], float] | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.repository_id = repository_id
        # Resolved once: every observed path is compared against this, so a
        # root that was itself a symlink must not make containment ambiguous.
        self._root = root.resolve()
        self._rules = rules
        self._on_batch = on_batch
        self._debouncer = debouncer or Debouncer()
        self._clock = clock or time.monotonic
        self._poll_interval = poll_interval_seconds
        self._lock = threading.Lock()
        self._observer: Any | None = None
        self._drain_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self.failure_count = 0
        self.last_error: str | None = None

    # -- policy ------------------------------------------------------------

    def note(self, path: Path, *, is_directory: bool) -> None:
        """Record an observed path as a candidate, if it is one at all."""
        relative = self._relative(path, is_directory=is_directory)
        if relative is None:
            return
        with self._lock:
            self._debouncer.record(relative, now=self._clock())

    def requeue(self, paths: tuple[str, ...]) -> None:
        """Put a batch back after it could not be handled.

        The paths are already known to be candidates, so they skip the filter
        and go straight back into the window.
        """
        with self._lock:
            now = self._clock()
            for path in paths:
                self._debouncer.record(path, now=now)

    def flush(self) -> None:
        """Dispatch whatever is pending, without waiting for the window."""
        with self._lock:
            batch = self._debouncer.flush()
        self._dispatch(batch)

    def tick(self) -> None:
        """One drain pass: dispatch the batch if it is due."""
        with self._lock:
            batch = self._debouncer.due(now=self._clock())
        self._dispatch(batch)

    def _dispatch(self, batch: tuple[str, ...] | None) -> None:
        if batch is None:
            return
        try:
            self._on_batch(batch)
        except Exception as error:
            # Deliberately broad. A reindex can fail for a hundred reasons — a
            # file vanishing mid-scan, a full disk, a parser timeout — and none
            # of them should stop the watcher permanently. Dying here would
            # leave the index silently stale, which is the failure this phase
            # exists to prevent. The count and the last error are exposed so a
            # persistent problem is visible in diagnostics rather than only in
            # a log nobody reads.
            self.failure_count += 1
            self.last_error = f"{type(error).__name__}: {error}"

    def _relative(self, path: Path, *, is_directory: bool) -> str | None:
        """The repository-relative path, or ``None`` if it is not a candidate."""
        try:
            resolved = path.resolve()
        except OSError:
            # A path that vanished before it could be resolved is not something
            # to reason about; the scan will see whatever is actually there.
            return None

        try:
            relative_path = resolved.relative_to(self._root)
        except ValueError:
            # Outside the approved root — a junction or symlink pointing away
            # from the tree. Canonicalized paths must stay inside the root
            # (`AGENTS.md` Section 4.4).
            return None

        relative = relative_path.as_posix()
        if relative in {"", "."}:
            # The root itself changed, which says nothing about any file.
            return None
        if self._rules.is_ignored(relative, is_directory=is_directory):
            return None
        return relative

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._observer is not None

    @property
    def pending(self) -> bool:
        """Whether changed paths are waiting for their window to close."""
        with self._lock:
            return self._debouncer.pending

    def start(self) -> None:
        """Begin watching. Idempotent."""
        if self._observer is not None:
            return

        # Imported here so that the debounce and path policy above stay usable
        # — and testable — without the dependency being loaded.
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                raw = event.src_path
                source = raw.decode() if isinstance(raw, bytes) else str(raw)
                watcher.note(Path(source), is_directory=bool(event.is_directory))
                # A move is two paths and the destination is the one that now
                # exists; missing it would leave the new location unindexed.
                destination = getattr(event, "dest_path", None)
                if destination:
                    moved = (
                        destination.decode()
                        if isinstance(destination, bytes)
                        else str(destination)
                    )
                    watcher.note(Path(moved), is_directory=bool(event.is_directory))

        observer = Observer()
        observer.schedule(_Handler(), str(self._root), recursive=True)
        observer.start()
        self._observer = observer

        self._stopping.clear()
        self._drain_thread = threading.Thread(
            target=self._drain,
            name=f"codeatlas-watch-{self.repository_id}",
            daemon=True,
        )
        self._drain_thread.start()

    def stop(self) -> None:
        """Stop watching and wait for the threads to finish. Idempotent."""
        self._stopping.set()
        # Anything noted moments before the stop is a real change; letting it
        # fall on the floor is exactly the silent staleness this phase exists
        # to prevent.
        self.flush()
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()
            observer.join(timeout=5.0)
        thread = self._drain_thread
        self._drain_thread = None
        if thread is not None:
            thread.join(timeout=5.0)

    def _drain(self) -> None:
        while not self._stopping.wait(self._poll_interval):
            self.tick()


__all__ = ["DEFAULT_POLL_INTERVAL_SECONDS", "BatchCallback", "RepositoryWatcher"]
