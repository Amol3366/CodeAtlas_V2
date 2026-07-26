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
from codeatlas.storage.sqlite.connection import write_transaction
from codeatlas.storage.sqlite.stores import (
    RepositoryStore,
    SearchStore,
    SnapshotStore,
)

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


class SnapshotRecoveryService:
    """Heals interrupted snapshots, rolls back, and enforces retention."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        search: SearchStore,
        connection: Connection,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._search = search
        self._connection = connection
        self._clock = clock or (lambda: datetime.now(UTC))

    def recover_interrupted(self) -> RecoveryReport:
        """Fail every snapshot left mid-build by a crashed process."""
        stranded = self._snapshots.list_by_states(sorted(NON_TERMINAL_STATES))
        if not stranded:
            return RecoveryReport()

        with write_transaction(self._connection):
            for snapshot in stranded:
                self._snapshots.set_state(snapshot.snapshot_id, SnapshotState.FAILED)

        return RecoveryReport(
            failed_snapshot_ids=tuple(item.snapshot_id for item in stranded)
        )

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
