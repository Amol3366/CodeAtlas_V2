"""Repository status and indexing diagnostics.

Status answers "how current is this?" and diagnostics answers "what does
CodeAtlas not know?" — the fourth and fifth questions in the product contract.
Both read the recorded state of the run that produced the active snapshot rather
than re-scanning, so what they report is what the snapshot was actually built
from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeatlas.contracts import SnapshotFreshness, SnapshotReference
from codeatlas.domain.errors import RepositoryNotFoundError
from codeatlas.domain.repository import Repository, ScanLimits
from codeatlas.storage.sqlite.stores import (
    FileStore,
    IndexJobStore,
    OpenJob,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)


@dataclass(frozen=True)
class RepositoryStatus:
    """What a repository currently knows."""

    repository: Repository
    snapshot: SnapshotReference | None
    file_count: int
    symbol_count: int
    parse_error_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class InterruptedRun:
    """An index run a killed process abandoned, as recovery found it.

    Reported so that a repository whose last index was interrupted does not
    look identical to one that was never indexed. The remedies differ: the
    first needs a reindex, the second needs a first index, and a user who
    cannot tell them apart cannot act on either (ADR-0007 decision 3).
    """

    snapshot_id: str
    stage: str
    started_at: str
    recovered_at: str


@dataclass(frozen=True)
class RepositoryDiagnostics:
    """What a repository deliberately excluded, and under which limits."""

    repository_id: str
    snapshot_id: str | None
    skipped_by_reason: dict[str, int]
    parse_error_count: int
    limits: ScanLimits
    warnings: tuple[str, ...]
    interrupted_run: InterruptedRun | None = None
    open_jobs: tuple[OpenJob, ...] = ()


class RepositoryStatusService:
    """Reports index freshness, coverage, and exclusions."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        jobs: IndexJobStore,
        limits: ScanLimits | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._files = files
        self._symbols = symbols
        self._jobs = jobs
        self._limits = limits or ScanLimits()

    def status(self, repository_id: str) -> RepositoryStatus:
        """Return the repository's active snapshot and coverage counts."""
        repository = self._require(repository_id)
        snapshot = self._snapshots.get_active(repository_id)
        if snapshot is None:
            return RepositoryStatus(
                repository=repository,
                snapshot=None,
                file_count=0,
                symbol_count=0,
                parse_error_count=0,
                warnings=("SNAPSHOT_NOT_READY",),
            )

        warnings = tuple(_recorded_warnings(self._jobs.latest_for(repository_id)))
        return RepositoryStatus(
            repository=repository,
            snapshot=SnapshotReference(
                snapshot_id=snapshot.snapshot_id,
                git_head=snapshot.git_head,
                working_tree_fingerprint=snapshot.working_tree_fingerprint,
                freshness=SnapshotFreshness.FRESH,
                semantic_coverage=0.0,
            ),
            file_count=snapshot.file_count,
            symbol_count=self._symbols.count_for_snapshot(snapshot.snapshot_id),
            parse_error_count=snapshot.parse_error_count,
            warnings=warnings,
        )

    def diagnostics(self, repository_id: str) -> RepositoryDiagnostics:
        """Return exclusions, limits, and recovery state from the last run."""
        self._require(repository_id)
        snapshot = self._snapshots.get_active(repository_id)
        recorded = self._jobs.latest_for(repository_id)

        return RepositoryDiagnostics(
            repository_id=repository_id,
            snapshot_id=snapshot.snapshot_id if snapshot else None,
            skipped_by_reason=_skipped_by_reason(recorded),
            parse_error_count=snapshot.parse_error_count if snapshot else 0,
            limits=self._limits,
            warnings=tuple(_recorded_warnings(recorded)),
            # Read from the *latest* job on purpose. Once a repository has been
            # indexed successfully its last run was not interrupted, and
            # continuing to report one would describe a condition that no
            # longer exists.
            interrupted_run=_interrupted_run(recorded),
            open_jobs=self._jobs.list_open(repository_id),
        )

    def _require(self, repository_id: str) -> Repository:
        repository = self._repositories.get(repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")
        return repository


def _recorded_warnings(recorded: Any) -> list[str]:
    if not isinstance(recorded, dict):
        return []
    warnings = recorded.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [str(warning) for warning in warnings]


def _interrupted_run(recorded: Any) -> InterruptedRun | None:
    if not isinstance(recorded, dict):
        return None
    found = recorded.get("recovered")
    if not isinstance(found, dict):
        return None
    return InterruptedRun(
        snapshot_id=str(found.get("snapshot_id", "")),
        stage=str(found.get("stage", "")),
        started_at=str(found.get("started_at", "")),
        recovered_at=str(found.get("recovered_at", "")),
    )


def _skipped_by_reason(recorded: Any) -> dict[str, int]:
    if not isinstance(recorded, dict):
        return {}
    skipped = recorded.get("skipped_by_reason")
    if not isinstance(skipped, dict):
        return {}
    return {str(key): int(value) for key, value in skipped.items()}
