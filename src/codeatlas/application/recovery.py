"""Snapshot recovery, rollback, and retention.

Three jobs, all in service of one rule: a user must never be left without a
usable snapshot.

* **Recovery** heals what a crashed process left behind. A snapshot stuck in a
  build state belongs to a process that no longer exists, so it is failed on the
  next service construction. The active snapshot is never touched — it was valid
  before the crash and remains valid after.
* **Rollback** promotes the previous snapshot back to active when a newly
  activated one turns out to be wrong. It is the escape hatch that makes
  activation safe to attempt.
* **Retention** keeps the database from growing without bound while guaranteeing
  rollback always has a target.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection

from codeatlas.domain.errors import NoRollbackTargetError, RepositoryNotFoundError
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.indexing.ownership import owner_is_live
from codeatlas.storage.sqlite.connection import to_utc_text, write_transaction
from codeatlas.storage.sqlite.stores import (
    IndexJobStore,
    RepositoryStore,
    SearchStore,
    SnapshotStore,
)

# Raised into diagnostics when a run is found abandoned. A repository whose
# last index was interrupted must not look identical to one that was never
# indexed: the remedies differ (ADR-0007 decision 3).
INTERRUPTED_RUN_WARNING = "INDEX_RUN_INTERRUPTED"

# States that only a running indexing job should ever hold. Finding one at rest
# means the process that owned it died.
NON_TERMINAL_STATES: frozenset[SnapshotState] = frozenset(
    {
        SnapshotState.DISCOVERED,
        SnapshotState.SCANNING,
        SnapshotState.PARSING,
        SnapshotState.CHUNKING,
        SnapshotState.INDEXING,
        SnapshotState.VALIDATING,
    }
)

# One superseded snapshot is retained so rollback always has somewhere to go.
RETAINED_SUPERSEDED_COUNT: int = 1


@dataclass(frozen=True)
class RecoveryReport:
    """What a recovery or pruning pass changed."""

    failed_snapshot_ids: tuple[str, ...] = ()
    deleted_snapshot_ids: tuple[str, ...] = ()
    failed_job_ids: tuple[str, ...] = ()


class SnapshotRecoveryService:
    """Heals interrupted snapshots, rolls back, and enforces retention."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        search: SearchStore,
        jobs: IndexJobStore,
        connection: Connection,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._search = search
        self._jobs = jobs
        self._connection = connection
        self._clock = clock or (lambda: datetime.now(UTC))

    def recover_interrupted(self) -> RecoveryReport:
        """Heal every index run abandoned by a process that no longer exists.

        Three things are left behind by a kill, and all three matter:

        * a **job row** stuck at ``running``. Nothing else clears it, and while
          it survives ``active_job_for`` reports an index in progress forever —
          blocking manual indexing, the watcher, and the reconciling scan
          alike. A repository killed once could never be indexed again.
        * a **snapshot** stuck mid-build, which Phase 2 already failed.
        * the snapshot's **derived rows**, including FTS projections that no
          foreign key can cascade to.

        What it does *not* touch is a run whose owner is still alive. Recovery
        runs inside ``build_services``, which is per request, while the watcher
        indexes on a background thread — so "fail everything unfinished" would
        abort the index running in the next thread over. Ownership is what
        makes the difference; see `codeatlas.indexing.ownership`.

        The report is persisted onto the job it describes rather than returned
        alone, because the process that discovers a crash is rarely the one
        asked about it later.
        """
        open_jobs = self._jobs.list_open()
        stranded_jobs = [job for job in open_jobs if not owner_is_live(job.owner)]

        # A snapshot claimed by a live job is being built right now. Every
        # other non-terminal snapshot is unowned: either its job is stranded
        # too, or it never had one.
        stranded_job_ids = {job.job_id for job in stranded_jobs}
        live = {
            job.snapshot_id
            for job in open_jobs
            if job.job_id not in stranded_job_ids
        }
        stranded_snapshots = [
            snapshot
            for snapshot in self._snapshots.list_by_states(sorted(NON_TERMINAL_STATES))
            if snapshot.snapshot_id not in live
        ]

        if not stranded_jobs and not stranded_snapshots:
            return RecoveryReport()

        recovered_at = to_utc_text(self._clock())
        with write_transaction(self._connection):
            for snapshot in stranded_snapshots:
                # The derived rows go, the snapshot row stays. A failed
                # snapshot can never be activated, so its rows are unreachable
                # — but "unreachable" is not "absent", and the FTS projections
                # are reachable by search. The row itself is kept because it is
                # the record of what failed.
                self._purge_derived_rows(snapshot.snapshot_id)
                self._snapshots.set_state(snapshot.snapshot_id, SnapshotState.FAILED)

            for job in stranded_jobs:
                self._jobs.finish(
                    job.job_id,
                    "failed",
                    {
                        "recovered": {
                            "snapshot_id": job.snapshot_id,
                            "stage": job.stage,
                            "started_at": job.started_at,
                            "recovered_at": recovered_at,
                        },
                        "warnings": [INTERRUPTED_RUN_WARNING],
                    },
                )

        return RecoveryReport(
            failed_snapshot_ids=tuple(
                item.snapshot_id for item in stranded_snapshots
            ),
            failed_job_ids=tuple(job.job_id for job in stranded_jobs),
        )

    def _purge_derived_rows(self, snapshot_id: str) -> None:
        """Delete everything that belonged to a snapshot except its own row.

        The foreign keys would cascade all of this if the snapshot row were
        deleted, so deleting the rows directly leaves the same absence — with
        the record intact. The FTS projections are cleared explicitly because
        virtual tables have no foreign keys for a cascade to follow.
        """
        self._search.delete_for_snapshot(snapshot_id)
        self._snapshots.delete_derived_rows(snapshot_id)

    def rollback(self, repository_id: str) -> Snapshot:
        """Restore the most recent superseded snapshot as active."""
        self._require_repository(repository_id)

        if self._snapshots.most_recent_superseded(repository_id) is None:
            raise NoRollbackTargetError(
                "There is no previous snapshot to roll back to."
            )

        with write_transaction(self._connection):
            restored_id = self._snapshots.rollback(repository_id, self._clock())

        restored = self._snapshots.get(restored_id)
        if restored is None:
            raise NoRollbackTargetError("The restored snapshot could not be read.")
        return restored

    def prune(self, repository_id: str) -> RecoveryReport:
        """Delete snapshots beyond the retention policy.

        Retains the active snapshot and the newest superseded one. Everything
        else — older superseded snapshots and failed ones — is deleted, and the
        foreign keys cascade to their derived rows.
        """
        self._require_repository(repository_id)

        superseded = self._snapshots.list_by_states(
            [SnapshotState.SUPERSEDED], repository_id
        )
        removable = [
            snapshot.snapshot_id
            for snapshot in superseded[RETAINED_SUPERSEDED_COUNT:]
        ]
        removable.extend(
            snapshot.snapshot_id
            for snapshot in self._snapshots.list_by_states(
                [SnapshotState.FAILED], repository_id
            )
        )
        if not removable:
            return RecoveryReport()

        with write_transaction(self._connection):
            for snapshot_id in removable:
                # The FTS projections are virtual tables with no foreign keys,
                # so a cascade cannot reach them. Clearing them here is what
                # keeps a pruned snapshot from leaving searchable orphans.
                self._search.delete_for_snapshot(snapshot_id)
                self._snapshots.delete(snapshot_id)

        return RecoveryReport(deleted_snapshot_ids=tuple(removable))

    def _require_repository(self, repository_id: str) -> None:
        if self._repositories.get(repository_id) is None:
            raise RepositoryNotFoundError("The repository is not registered.")
