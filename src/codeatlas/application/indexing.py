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
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from codeatlas.chunking.chunker import CHUNKER_VERSION, ChunkRequest, CodeChunker
from codeatlas.chunking.documents import DocumentChunker
from codeatlas.contracts import RepositoryRelativePath
from codeatlas.domain.chunks import LogicalChunk
from codeatlas.domain.errors import (
    CodeAtlasError,
    ErrorCode,
    IndexInProgressError,
    RepositoryNotFoundError,
)
from codeatlas.domain.ids import snapshot_id as build_snapshot_id
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.repository import FileRecord, ScanLimits
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.extraction.resolution import RESOLVER_VERSION, SnapshotResolver
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
    ChunkStore,
    FileStore,
    IndexJobStore,
    RelationStore,
    RepositoryStore,
    SearchStore,
    SnapshotStore,
    SymbolStore,
)

INDEX_VERSION: str = "1.0.0"

# Retention could not run. The snapshot is active and the answer is correct;
# what is unbounded is the database's growth, which is a support problem rather
# than a correctness one — so it is reported and does not fail the run.
RETENTION_FAILED_WARNING: str = "SNAPSHOT_RETENTION_FAILED"

# The semantic layer raised something the embedder itself did not expect. Like
# retention, it is reported and does not fail the run: the snapshot is already
# active and every deterministic channel answers without a vector.
EMBEDDING_FAILED_WARNING: str = "SEMANTIC_EMBEDDING_FAILED"

_RELATIVE_PATH_ADAPTER: TypeAdapter[str] = TypeAdapter(RepositoryRelativePath)


class SnapshotRetention(Protocol):
    """Just enough of the recovery service for indexing to enforce the bound.

    A protocol rather than the concrete service: indexing needs one method, and
    depending on the whole of recovery would make the direction of that
    dependency look larger than it is.
    """

    def prune(self, repository_id: str) -> object: ...


class SnapshotEmbedding(Protocol):
    """Just enough of the semantic layer for indexing to trigger it.

    A protocol, and a narrow one, for the reason that governs all of Phase 7:
    this module must not import the semantic package. Indexing is the
    deterministic path, and the deterministic path may not acquire a dependency
    — even an optional, lazily-imported one — on the layer that is allowed to
    be absent.
    """

    def embed_snapshot(self, repository_id: str, snapshot_id: str) -> object: ...


class SnapshotValidationError(CodeAtlasError):
    """A staged snapshot failed validation and must not be activated."""

    code = ErrorCode.INTERNAL_ERROR


@dataclass(frozen=True)
class ReuseStats:
    """What an indexing run reused versus recomputed.

    Reported rather than inferred: the phase claims that editing one symbol
    re-derives only what that edit touched, and a claim like that is worth only
    as much as the counter that proves it.
    """

    files_reused: int = 0
    files_reparsed: int = 0
    symbols_reused: int = 0
    chunks_reused: int = 0
    chunks_recomputed: int = 0
    references_reused: int = 0
    references_extracted: int = 0
    relations_resolved: int = 0


@dataclass(frozen=True)
class IndexResult:
    """The outcome of one indexing run."""

    job_id: str
    snapshot: Snapshot
    warnings: tuple[str, ...]
    skipped: tuple[SkippedFile, ...]
    diagnostics: tuple[ParseDiagnostic, ...]
    reuse: ReuseStats = ReuseStats()


class IndexRepositoryService:
    """Builds and activates deterministic snapshots of a repository."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        jobs: IndexJobStore,
        chunks: ChunkStore,
        search: SearchStore,
        relations: RelationStore,
        scanner: RepositoryScanner,
        git: GitAdapter,
        registry: ParserRegistry,
        connection: Connection,
        clock: Callable[[], datetime] | None = None,
        limits: ScanLimits | None = None,
        retention: SnapshotRetention | None = None,
        embedding: SnapshotEmbedding | None = None,
    ) -> None:
        self._retention = retention
        self._embedding = embedding
        self._repositories = repositories
        self._snapshots = snapshots
        self._files = files
        self._symbols = symbols
        self._jobs = jobs
        self._chunks = chunks
        self._search = search
        self._relations = relations
        self._resolver = SnapshotResolver()
        self._code_chunker = CodeChunker()
        self._document_chunker = DocumentChunker()
        self._scanner = scanner
        self._git = git
        self._registry = registry
        self._connection = connection
        self._clock = clock or (lambda: datetime.now(UTC))
        self._limits = limits or ScanLimits()

    def _apply_retention(
        self, repository_id: str, warnings: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Drop snapshots beyond the retention policy, after activation.

        Retention runs here rather than in any one adapter so the bound holds
        for every caller — CLI, API, watcher, reconciling scan. Left to the
        callers it would be one more thing each had to remember, and the
        watcher is precisely the caller that indexes without anyone watching.

        Failure is a **warning, not an error**. The new snapshot is already
        active by this point; turning a housekeeping failure into a failed
        index would report a good snapshot as a bad one and send the next run
        off to rebuild it.
        """
        if self._retention is None:
            return warnings
        try:
            self._retention.prune(repository_id)
        except Exception:
            return (*warnings, RETENTION_FAILED_WARNING)
        return warnings

    def _apply_embedding(
        self, repository_id: str, snapshot_id: str, warnings: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Bring semantic coverage up to date, after activation.

        Everything about the placement is deliberate. It runs *after* the
        snapshot is active, so exact, lexical, graph, and Git retrieval are
        already serving before a single vector exists — Section 4.2's
        requirement that deterministic retrieval stay available while semantic
        indexing is incomplete.

        And it cannot fail the run. The embedder already returns warnings
        rather than raising for the failures it anticipates; this catch is for
        the ones it does not. Turning either into a failed index would report a
        good snapshot as a bad one over a layer the product does not need to
        answer.
        """
        if self._embedding is None:
            return warnings
        try:
            self._embedding.embed_snapshot(repository_id, snapshot_id)
        except Exception:
            return (*warnings, EMBEDDING_FAILED_WARNING)
        return warnings

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
            CHUNKER_VERSION,
            RESOLVER_VERSION,
        )

        # Reuse is only sound against the previous *active* snapshot, and only
        # when the logic that produced its rows is the logic running now.
        previous = self._snapshots.get_active(repository_id_value)
        reusable = self._reusable_files(previous, scan.files)

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

        if existing is not None:
            # A previous attempt at these exact inputs died or failed. Its rows
            # are unreachable by definition, and leaving them would make the
            # retry collide on the snapshot's primary key, so the abandoned
            # attempt is cleared before this one stages. The FTS projections are
            # virtual tables with no foreign keys, so they are cleared
            # explicitly rather than by cascade.
            with write_transaction(self._connection):
                self._search.delete_for_snapshot(snapshot_id)
                self._snapshots.delete(snapshot_id)

        self._jobs.set_snapshot(job_id, snapshot_id)
        parsed = self._parse_files(
            repository_id_value, snapshot_id, root, scan, skip=reusable
        )
        chunked = self._chunk_files(
            repository_id_value, root, scan, parsed, skip=reusable
        )

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
            chunker_version=CHUNKER_VERSION,
            resolver_version=RESOLVER_VERSION,
        )

        reuse = self._stage(
            snapshot=snapshot,
            files=scan.files,
            symbols=parsed.symbols,
            chunks=chunked,
            references=parsed.references,
            previous=previous,
            reusable=reusable,
        )
        self._jobs.update_stage(job_id, "validating", "running")

        try:
            self._validate_snapshot(
                snapshot_id, expected_file_count=len(scan.files)
            )
        except BaseException:
            self._snapshots.set_state(snapshot_id, SnapshotState.FAILED)
            self._jobs.finish(
                job_id, "failed", {"error": "SNAPSHOT_VALIDATION_FAILED"}
            )
            raise

        activated_at = self._clock()
        with write_transaction(self._connection):
            self._snapshots.activate(snapshot_id, activated_at)

        warnings = self._apply_retention(repository_id_value, warnings)
        warnings = self._apply_embedding(repository_id_value, snapshot_id, warnings)

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
                "reuse": {
                    "files_reused": reuse.files_reused,
                    "files_reparsed": reuse.files_reparsed,
                    "symbols_reused": reuse.symbols_reused,
                    "chunks_reused": reuse.chunks_reused,
                    "chunks_recomputed": reuse.chunks_recomputed,
                    "references_reused": reuse.references_reused,
                    "references_extracted": reuse.references_extracted,
                    "relations_resolved": reuse.relations_resolved,
                },
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
            reuse=reuse,
        )

    def _parse_files(
        self,
        repository_id_value: str,
        snapshot_id: str,
        root: Path,
        scan: ScanResult,
        skip: frozenset[str],
    ) -> _ParseOutcome:
        symbols: list[SymbolRecord] = []
        references: list[SymbolReference] = []
        diagnostics: list[ParseDiagnostic] = []
        contents: dict[str, bytes] = {}
        parsed_file_count = 0
        parse_error_count = 0

        for record in scan.files:
            if record.file_id in skip:
                # Byte-identical to the previous active snapshot: its symbols
                # and chunks are copied instead of re-derived.
                continue
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
            references.extend(result.references)
            diagnostics.extend(result.diagnostics)
            contents[record.file_id] = content

        return _ParseOutcome(
            symbols=tuple(symbols),
            references=tuple(references),
            diagnostics=tuple(diagnostics),
            contents=contents,
            parsed_file_count=parsed_file_count,
            parse_error_count=parse_error_count,
        )

    def _reusable_files(
        self, previous: Snapshot | None, files: tuple[FileRecord, ...]
    ) -> frozenset[str]:
        """File IDs whose derived rows may be copied from ``previous``.

        Reuse requires three things to line up: an active predecessor, the same
        parser and chunker that produced its rows, and a file whose content hash
        is unchanged. Any mismatch means the derived content is no longer
        comparable, and comparing it anyway is how stale rows reach a snapshot.
        """
        if previous is None or previous.state is not SnapshotState.ACTIVE:
            return frozenset()
        if previous.parser_bundle_version != PARSER_BUNDLE_VERSION:
            return frozenset()
        if previous.chunker_version != CHUNKER_VERSION:
            return frozenset()
        if previous.resolver_version != RESOLVER_VERSION:
            return frozenset()

        earlier = {
            record.file_id: record
            for record in self._files.list_for_snapshot(previous.snapshot_id)
        }
        return frozenset(
            record.file_id
            for record in files
            if record.file_id in earlier
            and earlier[record.file_id].content_hash == record.content_hash
        )

    def _chunk_files(
        self,
        repository_id_value: str,
        root: Path,
        scan: ScanResult,
        parsed: _ParseOutcome,
        skip: frozenset[str],
    ) -> tuple[LogicalChunk, ...]:
        """Chunk the files that were actually parsed in this run."""
        by_file: dict[str, list[SymbolRecord]] = {}
        for symbol in parsed.symbols:
            by_file.setdefault(symbol.file_id, []).append(symbol)

        chunks: list[LogicalChunk] = []
        for record in scan.files:
            if record.file_id in skip:
                continue
            content = parsed.contents.get(record.file_id)
            if content is None:
                continue
            chunker = (
                self._code_chunker
                if record.language == "python"
                else self._document_chunker
            )
            chunks.extend(
                chunker.chunk(
                    ChunkRequest(
                        repository_id=repository_id_value,
                        file=record,
                        content=content,
                        symbols=tuple(by_file.get(record.file_id, ())),
                    )
                )
            )
        return tuple(chunks)

    def _stage(
        self,
        *,
        snapshot: Snapshot,
        files: tuple[FileRecord, ...],
        symbols: tuple[SymbolRecord, ...],
        chunks: tuple[LogicalChunk, ...],
        references: tuple[SymbolReference, ...],
        previous: Snapshot | None,
        reusable: frozenset[str],
    ) -> ReuseStats:
        paths_by_file_id = {record.file_id: record.relative_path for record in files}
        reused_symbols = 0
        reused_chunks = 0

        with write_transaction(self._connection):
            self._snapshots.add_staging(snapshot)
            self._files.add_many(snapshot.snapshot_id, files)
            self._symbols.add_many(snapshot.snapshot_id, symbols)
            self._chunks.add_many(snapshot.snapshot_id, chunks)
            self._search.index_chunks(
                snapshot.snapshot_id, chunks, paths_by_file_id
            )

            if previous is not None and reusable:
                file_ids = sorted(reusable)
                reused_symbols = self._symbols.copy_from_snapshot(
                    previous.snapshot_id, snapshot.snapshot_id, file_ids
                )
                reused_chunks = self._chunks.copy_from_snapshot(
                    previous.snapshot_id, snapshot.snapshot_id, file_ids
                )
                self._search.copy_from_snapshot(
                    previous.snapshot_id, snapshot.snapshot_id, file_ids
                )

            self._search.index_files(snapshot.snapshot_id, files)
            self._snapshots.set_state(snapshot.snapshot_id, SnapshotState.INDEXING)

        resolution = self._resolve(
            snapshot=snapshot,
            files=files,
            references=references,
            previous=previous,
            reusable=reusable,
        )

        return ReuseStats(
            files_reused=len(reusable),
            files_reparsed=len(files) - len(reusable),
            symbols_reused=reused_symbols,
            chunks_reused=reused_chunks,
            chunks_recomputed=len(chunks),
            references_reused=resolution.references_reused,
            references_extracted=len(references),
            relations_resolved=resolution.relations_resolved,
        )

    def _resolve(
        self,
        *,
        snapshot: Snapshot,
        files: tuple[FileRecord, ...],
        references: tuple[SymbolReference, ...],
        previous: Snapshot | None,
        reusable: frozenset[str],
    ) -> _ResolutionOutcome:
        """Resolve the whole snapshot's references into relations.

        An unchanged file's *references* are reused — they are a pure function
        of bytes that did not change. Its *targets* are not: they are recomputed
        along with everything else, every run. That asymmetry is the whole point
        of the two-stage design, and it is why an edge can never outlive the
        symbol it points at.
        """
        self._snapshots.set_state(snapshot.snapshot_id, SnapshotState.RESOLVING)

        carried: list[SymbolReference] = []
        if previous is not None and reusable:
            carried = [
                relation.as_reference()
                for relation in self._relations.list_for_snapshot(
                    previous.snapshot_id
                )
                if relation.file_id in reusable
                # A derived edge — `TESTS`, or a document edge combined from
                # several references — was never stated by one file, so there is
                # no reference to carry. It is re-derived instead.
                and not relation.is_derived
            ]

        symbols = self._symbols.list_for_snapshot(snapshot.snapshot_id)
        relations, stats = self._resolver.resolve(
            files, symbols, [*carried, *references]
        )

        with write_transaction(self._connection):
            self._relations.add_many(snapshot.snapshot_id, relations)
            self._snapshots.set_state(snapshot.snapshot_id, SnapshotState.INDEXING)

        return _ResolutionOutcome(
            references_reused=len(carried),
            relations_resolved=stats.references,
        )

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
        if not snapshot.chunker_version:
            raise SnapshotValidationError("The staged snapshot is missing versions.")

        # Reusing a row is not a reason to trust it less, so copied chunks face
        # exactly the same checks as freshly derived ones.
        if self._chunks.invalid_line_ranges(snapshot_id):
            raise SnapshotValidationError(
                "A staged chunk has a line range outside its file."
            )
        if self._chunks.orphan_membership(snapshot_id):
            raise SnapshotValidationError(
                "A membership row references a chunk that is not in the snapshot."
            )

        chunk_rows, projection_rows = self._search.count_indexed(snapshot_id)
        if chunk_rows != projection_rows:
            raise SnapshotValidationError(
                "The search projection does not cover every chunk."
            )
        if self._chunks.count_membership(snapshot_id) != chunk_rows:
            raise SnapshotValidationError(
                "Chunk membership does not cover every chunk."
            )

        if not snapshot.resolver_version:
            raise SnapshotValidationError("The staged snapshot is missing versions.")

        # Gate condition 7: a cross-file edge cannot survive into a snapshot
        # whose endpoint symbol no longer exists. Checked here rather than
        # trusted from resolution, because "cannot happen" is a claim worth
        # verifying against the database that will actually serve queries.
        if self._relations.dangling_endpoints(snapshot_id):
            raise SnapshotValidationError(
                "A staged relation references a symbol outside the snapshot."
            )
        if self._relations.invalid_line_ranges(snapshot_id):
            raise SnapshotValidationError(
                "A staged relation has a line range outside its file."
            )

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
class _ResolutionOutcome:
    references_reused: int
    relations_resolved: int


@dataclass(frozen=True)
class _ParseOutcome:
    symbols: tuple[SymbolRecord, ...]
    references: tuple[SymbolReference, ...]
    diagnostics: tuple[ParseDiagnostic, ...]
    contents: dict[str, bytes]
    parsed_file_count: int
    parse_error_count: int
