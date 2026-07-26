"""Addressable entities: evidence, files, and symbols by ID.

Phase 5's citations need a durable address for a piece of evidence, and evidence
IDs are content-derived hashes that cannot be reversed. So they are persisted —
but only their *location*, never their text.

Fetching re-reads the file from disk and re-verifies the recorded hash, exactly
as query-time evidence already does. That is the whole design: a stored row can
point at a region, but it can never become a second, staler answer about what
that region contains. When the file has drifted, the fetch says so instead of
returning content that no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.evidence import (
    EvidenceBuilder,
    EvidenceCandidate,
    snapshot_reference,
)
from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    QueryResponse,
    SnapshotReference,
)
from codeatlas.domain.errors import (
    EvidenceNotFoundError,
    FileNotFoundInSnapshotError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
    SymbolNotFoundError,
)
from codeatlas.domain.repository import FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.storage.sqlite.stores import (
    EvidenceStore,
    FileStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)


@dataclass(frozen=True)
class FileDetail:
    """One file of the active snapshot, with its snapshot stated."""

    snapshot: SnapshotReference
    file: FileRecord


@dataclass(frozen=True)
class SymbolDetail:
    """One symbol of the active snapshot, with its file path resolved."""

    snapshot: SnapshotReference
    symbol: SymbolRecord
    file_path: str


class EntityService:
    """Resolves an opaque ID back to a verified entity."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        evidence: EvidenceStore,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._files = files
        self._symbols = symbols
        self._evidence_store = evidence
        self._builder = EvidenceBuilder(files, evidence)

    def get_evidence(self, repository_id: str, evidence_id: str) -> QueryResponse:
        """Re-verify and return one stored evidence region."""
        repository, snapshot = self._active(repository_id)
        stored = self._evidence_store.get(snapshot.snapshot_id, evidence_id)
        if stored is None:
            raise EvidenceNotFoundError(
                "No such evidence in the active snapshot."
            )

        built = self._builder.build(
            repository_root=Path(repository.canonical_root),
            snapshot=snapshot,
            candidates=[
                EvidenceCandidate(
                    file_id=stored.file_id,
                    start_line=stored.start_line,
                    end_line=stored.end_line,
                    derivation=stored.derivation,
                    confidence=1.0,
                )
            ],
        )

        if not built.evidence:
            # The region still exists on paper, but the file no longer hashes to
            # what the snapshot recorded. Reporting drift is the only honest
            # answer; returning the stored range would cite lines that may now
            # contain something else entirely.
            return QueryResponse(
                request_id=evidence_id,
                repository_id=repository_id,
                snapshot=snapshot_reference(snapshot, stale=True),
                answer=Answer(
                    summary=(
                        "The cited file has changed since this evidence was"
                        " recorded, so its content can no longer be verified."
                    ),
                    claims=[],
                ),
                evidence=[],
                warnings=list(built.warnings) or ["EVIDENCE_STALE_FILE_CONTENT"],
            )

        item = built.evidence[0]
        return QueryResponse(
            request_id=evidence_id,
            repository_id=repository_id,
            snapshot=snapshot_reference(snapshot, stale=built.stale),
            answer=Answer(
                summary=(
                    f"{item.file_path} lines {item.start_line}-{item.end_line}"
                    " in the active snapshot."
                ),
                claims=[
                    Claim(
                        claim_id="c1",
                        text=(
                            f"{item.file_path} lines {item.start_line}-"
                            f"{item.end_line} match the recorded content hash."
                        ),
                        derivation=Derivation.DETERMINISTIC,
                        confidence=1.0,
                        evidence_ids=[item.evidence_id],
                    )
                ],
            ),
            evidence=list(built.evidence),
            warnings=list(built.warnings),
        )

    def get_file(self, repository_id: str, file_id: str) -> FileDetail:
        _, snapshot = self._active(repository_id)
        record = self._files.get(snapshot.snapshot_id, file_id)
        if record is None:
            raise FileNotFoundInSnapshotError(
                "No such file in the active snapshot."
            )
        return FileDetail(
            snapshot=snapshot_reference(snapshot, stale=False), file=record
        )

    def get_symbol(self, repository_id: str, symbol_id: str) -> SymbolDetail:
        _, snapshot = self._active(repository_id)
        match = next(
            (
                symbol
                for symbol in self._symbols.list_for_snapshot(snapshot.snapshot_id)
                if symbol.symbol_id == symbol_id
            ),
            None,
        )
        if match is None:
            raise SymbolNotFoundError("No such symbol in the active snapshot.")

        record = self._files.get(snapshot.snapshot_id, match.file_id)
        return SymbolDetail(
            snapshot=snapshot_reference(snapshot, stale=False),
            symbol=match,
            file_path=record.relative_path if record is not None else "",
        )

    def _active(self, repository_id: str) -> tuple[Repository, Snapshot]:
        repository = self._repositories.get(repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")
        snapshot = self._snapshots.get_active(repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot. Index it first."
            )
        return repository, snapshot
