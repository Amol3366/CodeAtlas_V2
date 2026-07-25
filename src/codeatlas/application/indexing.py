"""Repository indexing: scan, parse, stage, validate, activate.

The ordering here is the freshness contract in executable form. A snapshot is
built in staging, validated in full, and only then activated inside a single
transaction that supersedes its predecessor. Anything that fails leaves the
previous active snapshot exactly as it was, because a stale-but-valid answer is
strictly better than a partially built one.

Parsing, Git, and filesystem work all happen outside the write transaction. The
transaction covers only the row writes and the activation swap, keeping it short
as `CLAUDE.md` Section 15 requires.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from pydantic import TypeAdapter, ValidationError

from codeatlas.contracts import RepositoryRelativePath
from codeatlas.domain.errors import (
    CodeAtlasError,
    ErrorCode,
    IndexInProgressError,
    RepositoryNotFoundError,
)
from codeatlas.domain.ids import snapshot_id as build_snapshot_id
from codeatlas.domain.repository import FileRecord, ScanLimits
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.registry import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParserRegistry,
)
from codeatlas.repositories.git_state import GitAdapter
from codeatlas.repositories.ignore_rules import IgnoreRules
from codeatlas.repositories.scanner import RepositoryScanner, ScanResult, SkippedFile
from codeatlas.storage.sqlite.connection import write_transaction
from codeatlas.storage.sqlite.stores import (
    FileStore,
    IndexJobStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)

INDEX_VERSION: str = "1.0.0"

_RELATIVE_PATH_ADAPTER: TypeAdapter[str] = TypeAdapter(RepositoryRelativePath)


class SnapshotValidationError(CodeAtlasError):
    """A staged snapshot failed validation and must not be activated."""

    code = ErrorCode.INTERNAL_ERROR


@dataclass(frozen=True)
class IndexResult:
    """The outcome of one indexing run."""

    job_id: str
    snapshot: Snapshot
    warnings: tuple[str, ...]
    skipped: tuple[SkippedFile, ...]
    diagnostics: tuple[ParseDiagnostic, ...]


class IndexRepositoryService:
    """Builds and activates deterministic snapshots of a repository."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        jobs: IndexJobStore,
        scanner: RepositoryScanner,
        git: GitAdapter,
        registry: ParserRegistry,
        connection: Connection,
        clock: Callable[[], datetime] | None = None,
        limits: ScanLimits | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._files = files
        self._symbols = symbols
        self._jobs = jobs
        self._scanner = scanner
        self._git = git
        self._registry = registry
        self._connection = connection
        self._clock = clock or (lambda: datetime.now(UTC))
        self._limits = limits or ScanLimits()

    def index(self, repository_id_value: str) -> IndexResult:
        """Scan, parse, stage, validate, and activate a snapshot."""
        repository = self._repositories.get(repository_id_value)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")

        if self._jobs.active_job_for(repository_id_value) is not None:
            raise IndexInProgressError(
                "An indexing job is already running for this repository."
            )

        root = Path(repository.canonical_root)
        job_id = f"job_{uuid.uuid4().hex}"
        self._jobs.start(job_id, repository_id_value, "")

        try:
            return self._run(job_id, repository_id_value, root)
        except BaseException as error:
            self._jobs.finish(job_id, "failed", {"error": type(error).__name__})
            raise

    def _run(self, job_id: str, repository_id_value: str, root: Path) -> IndexResult:
        rules = IgnoreRules.load(root)
        scan = self._scanner.scan(root, rules)

        self._jobs.update_stage(job_id, "parsing", "running")
        git_state = self._git.read_state(root)
        warnings = tuple(scan.warnings) + tuple(git_state.warnings)

        snapshot_id = build_snapshot_id(
            repository_id_value,
            scan.working_tree_fingerprint,
            PARSER_BUNDLE_VERSION,
            INDEX_VERSION,
        )

        existing = self._snapshots.get(snapshot_id)
        if existing is not None and existing.state is SnapshotState.ACTIVE:
            # Identical inputs and identical logic produce an identical snapshot,
            # so re-indexing an unchanged tree is a no-op rather than a rebuild.
            self._jobs.set_snapshot(job_id, snapshot_id)
            self._jobs.finish(
                job_id,
                "succeeded",
                {
                    "outcome": "skipped_unchanged",
                    "warnings": list(warnings),
                    "skipped_by_reason": _skipped_by_reason(scan.skipped),
                },
            )
            return IndexResult(
                job_id=job_id,
                snapshot=existing,
                warnings=(*warnings, "INDEX_SKIPPED_UNCHANGED"),
                skipped=scan.skipped,
                diagnostics=(),
            )

        self._jobs.set_snapshot(job_id, snapshot_id)
        parsed = self._parse_files(repository_id_value, snapshot_id, root, scan)

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            repository_id=repository_id_value,
            state=SnapshotState.PARSING,
            git_head=git_state.head_commit,
            git_branch=git_state.branch,
            git_dirty=git_state.is_dirty,
            working_tree_fingerprint=scan.working_tree_fingerprint,
            file_count=len(scan.files),
            parsed_file_count=parsed.parsed_file_count,
            skipped_file_count=len(scan.skipped),
            parse_error_count=parsed.parse_error_count,
            parser_bundle_version=PARSER_BUNDLE_VERSION,
            index_version=INDEX_VERSION,
            created_at=self._clock(),
            activated_at=None,
        )

        self._stage(snapshot, scan.files, parsed.symbols)
        self._jobs.update_stage(job_id, "validating", "running")

        try:
            self._validate_snapshot(snapshot_id, expected_file_count=len(scan.files))
        except BaseException:
            self._snapshots.set_state(snapshot_id, SnapshotState.FAILED)
            self._jobs.finish(
                job_id, "failed", {"error": "SNAPSHOT_VALIDATION_FAILED"}
            )
            raise

        activated_at = self._clock()
        with write_transaction(self._connection):
            self._snapshots.activate(snapshot_id, activated_at)

        self._jobs.finish(
            job_id,
            "succeeded",
            {
                "outcome": "activated",
                "warnings": list(warnings),
                "skipped_by_reason": _skipped_by_reason(scan.skipped),
                "parse_diagnostics": [
                    diagnostic.code for diagnostic in parsed.diagnostics
                ],
            },
        )
        active = self._snapshots.get(snapshot_id)
        if active is None:
            # Unreachable unless the activation transaction was rolled back
            # underneath us; treat it as a validation failure rather than
            # returning a snapshot the database does not agree exists.
            raise SnapshotValidationError("The activated snapshot could not be read.")
        return IndexResult(
            job_id=job_id,
            snapshot=active,
            warnings=warnings,
            skipped=scan.skipped,
            diagnostics=parsed.diagnostics,
        )

    def _parse_files(
        self,
        repository_id_value: str,
        snapshot_id: str,
        root: Path,
        scan: ScanResult,
    ) -> _ParseOutcome:
        symbols: list[SymbolRecord] = []
        diagnostics: list[ParseDiagnostic] = []
        parsed_file_count = 0
        parse_error_count = 0

        for record in scan.files:
            parser = self._registry.parser_for(record.language)
            if parser is None:
                continue

            try:
                content = (root / record.relative_path).read_bytes()
            except OSError:
                parse_error_count += 1
                diagnostics.append(
                    ParseDiagnostic(
                        code="PARSE_UNREADABLE",
                        message=f"{record.relative_path} could not be read.",
                    )
                )
                continue

            result = parser.parse(
                ParseRequest(
                    repository_id=repository_id_value,
                    snapshot_id=snapshot_id,
                    file_id=record.file_id,
                    relative_path=record.relative_path,
                    language=record.language,
                    content=content,
                )
            )
            parsed_file_count += 1
            if not result.success:
                parse_error_count += 1
            symbols.extend(result.symbols)
            diagnostics.extend(result.diagnostics)

        return _ParseOutcome(
            symbols=tuple(symbols),
            diagnostics=tuple(diagnostics),
            parsed_file_count=parsed_file_count,
            parse_error_count=parse_error_count,
        )

    def _stage(
        self,
        snapshot: Snapshot,
        files: tuple[FileRecord, ...],
        symbols: tuple[SymbolRecord, ...],
    ) -> None:
        with write_transaction(self._connection):
            self._snapshots.add_staging(snapshot)
            self._files.add_many(snapshot.snapshot_id, files)
            self._symbols.add_many(snapshot.snapshot_id, symbols)
            self._snapshots.set_state(snapshot.snapshot_id, SnapshotState.INDEXING)

    def _validate_snapshot(self, snapshot_id: str, *, expected_file_count: int) -> None:
        """Reject anything that must never reach an active snapshot."""
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise SnapshotValidationError("The staged snapshot is missing.")

        stored_files = self._files.list_for_snapshot(snapshot_id)
        if len(stored_files) != expected_file_count:
            raise SnapshotValidationError(
                "The staged file count does not match the scan."
            )

        for record in stored_files:
            try:
                _RELATIVE_PATH_ADAPTER.validate_python(record.relative_path)
            except ValidationError as error:
                raise SnapshotValidationError(
                    "A staged file path is not a valid repository-relative path."
                ) from error

        invalid = self._symbols.invalid_line_ranges(snapshot_id)
        if invalid:
            raise SnapshotValidationError(
                "A staged symbol has a line range outside its file."
            )

        if not snapshot.parser_bundle_version or not snapshot.index_version:
            raise SnapshotValidationError("The staged snapshot is missing versions.")

    def get_active_snapshot(self, repository_id_value: str) -> Snapshot | None:
        """Return the repository's active snapshot, if any."""
        return self._snapshots.get_active(repository_id_value)

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        """Return any snapshot by ID, regardless of state."""
        return self._snapshots.get(snapshot_id)

    def symbol_count(self, snapshot_id: str) -> int:
        """Return how many symbols a snapshot holds."""
        return self._symbols.count_for_snapshot(snapshot_id)

    def list_files(self, snapshot_id: str) -> tuple[FileRecord, ...]:
        """Return a snapshot's files."""
        return self._files.list_for_snapshot(snapshot_id)


def _skipped_by_reason(skipped: tuple[SkippedFile, ...]) -> dict[str, int]:
    """Aggregate skip reasons so diagnostics stay bounded on large repos."""
    counts: dict[str, int] = {}
    for record in skipped:
        counts[record.reason_code] = counts.get(record.reason_code, 0) + 1
    return counts


@dataclass(frozen=True)
class _ParseOutcome:
    symbols: tuple[SymbolRecord, ...]
    diagnostics: tuple[ParseDiagnostic, ...]
    parsed_file_count: int
    parse_error_count: int
