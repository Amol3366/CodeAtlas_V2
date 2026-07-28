"""Typed persistence for repositories, snapshots, files, symbols, and jobs.

Every statement is parameterized; no identifier or value is ever interpolated
into SQL. Stores translate between rows and domain types and hold no policy of
their own — sequencing, validation, and activation ordering belong to the
application services.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from codeatlas.contracts import (
    AnalysisSide,
    AnalysisStateRef,
    ChangeAnalysisKind,
    ChangeAnalysisReport,
    ChangeAnalysisStatus,
    ChangedFile,
    ChangedSymbol,
    ChangeEvidenceItem,
    ChangeKind,
    Derivation,
    Finding,
    MessageRole,
    MessageStatus,
    OverallRisk,
    RelationKind,
    RunStatus,
    Severity,
    SnapshotFreshness,
    SymbolKind,
)
from codeatlas.contracts import ImpactEdge as ContractImpactEdge
from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.conversations import (
    MAX_MESSAGE_CONTENT_BYTES,
    MAX_WARNINGS_BYTES,
    ConversationRecord,
    MessageEvidenceRow,
    MessageRecord,
    Page,
    RunRecord,
)
from codeatlas.domain.relations import (
    RelationRecord,
    ResolutionState,
    StoredEvidence,
)
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.search import ChunkSearchHit, FileSearchHit
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.domain.symbols import SymbolRecord, Visibility
from codeatlas.storage.sqlite.connection import from_utc_text, to_utc_text

_ACTIVE_JOB_STATUSES = ("queued", "running")

# Columns a caller may restrict a chunk search to. A column filter is FTS
# syntax, so the name can only ever come from this fixed set.
_SEARCHABLE_CHUNK_COLUMNS = frozenset({"file_path", "symbol_name", "content"})

# Chunks are always read through their file so ordering is stable across runs:
# path, then position in the file, then part of a split symbol.
_CHUNK_SELECT = (
    "SELECT chunks.* FROM chunks"
    " JOIN files ON files.snapshot_id = chunks.snapshot_id"
    "   AND files.file_id = chunks.file_id"
)
_CHUNK_ORDER = "ORDER BY files.relative_path, chunks.start_line, chunks.part_index"

# Relations are ordered by call site so traversal is reproducible: the same
# snapshot must always produce the same answer in the same order.
_RELATION_ORDER = "ORDER BY start_line, end_line, kind, relation_id"


class RepositoryStore:
    """Registered repositories."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, repository: Repository) -> None:
        self._connection.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES (?, ?, ?, ?)",
            (
                repository.repository_id,
                repository.display_name,
                repository.canonical_root,
                to_utc_text(repository.created_at),
            ),
        )

    def get(self, repository_id: str) -> Repository | None:
        row = self._connection.execute(
            "SELECT * FROM repositories WHERE repository_id = ?",
            (repository_id,),
        ).fetchone()
        return _repository_from_row(row) if row is not None else None

    def get_by_root(self, canonical_root: str) -> Repository | None:
        row = self._connection.execute(
            "SELECT * FROM repositories WHERE canonical_root = ?",
            (canonical_root,),
        ).fetchone()
        return _repository_from_row(row) if row is not None else None

    def list_all(self) -> tuple[Repository, ...]:
        rows = self._connection.execute(
            "SELECT * FROM repositories ORDER BY display_name, repository_id"
        ).fetchall()
        return tuple(_repository_from_row(row) for row in rows)

    def set_watch_enabled(self, repository_id: str, *, enabled: bool) -> None:
        """Turn continuous freshness on or off for one repository."""
        self._connection.execute(
            "UPDATE repositories SET watch_enabled = ? WHERE repository_id = ?",
            (1 if enabled else 0, repository_id),
        )

    def list_watched(self) -> tuple[Repository, ...]:
        """Every repository the watcher should be running for."""
        rows = self._connection.execute(
            "SELECT * FROM repositories WHERE watch_enabled = 1"
            " ORDER BY display_name, repository_id"
        ).fetchall()
        return tuple(_repository_from_row(row) for row in rows)


class SnapshotStore:
    """Snapshot lifecycle persistence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_staging(self, snapshot: Snapshot) -> None:
        """Insert a snapshot that is being built. It is not visible to queries."""
        self._connection.execute(
            "INSERT INTO snapshots ("
            " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
            " working_tree_fingerprint, file_count, parsed_file_count,"
            " skipped_file_count, parse_error_count, parser_bundle_version,"
            " index_version, created_at, activated_at, chunker_version,"
            " resolver_version"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.repository_id,
                snapshot.state.value,
                snapshot.git_head,
                snapshot.git_branch,
                int(snapshot.git_dirty),
                snapshot.working_tree_fingerprint,
                snapshot.file_count,
                snapshot.parsed_file_count,
                snapshot.skipped_file_count,
                snapshot.parse_error_count,
                snapshot.parser_bundle_version,
                snapshot.index_version,
                to_utc_text(snapshot.created_at),
                to_utc_text(snapshot.activated_at) if snapshot.activated_at else None,
                snapshot.chunker_version,
                snapshot.resolver_version,
            ),
        )

    def set_state(self, snapshot_id: str, state: SnapshotState) -> None:
        self._connection.execute(
            "UPDATE snapshots SET state = ? WHERE snapshot_id = ?",
            (state.value, snapshot_id),
        )

    def update_counts(
        self,
        snapshot_id: str,
        *,
        parsed_file_count: int,
        parse_error_count: int,
    ) -> None:
        self._connection.execute(
            "UPDATE snapshots"
            " SET parsed_file_count = ?, parse_error_count = ?"
            " WHERE snapshot_id = ?",
            (parsed_file_count, parse_error_count, snapshot_id),
        )

    def activate(self, snapshot_id: str, activated_at: datetime) -> None:
        """Supersede the current active snapshot and activate this one.

        The caller wraps this in a write transaction so the swap is atomic: a
        reader never sees zero or two active snapshots.
        """
        row = self._connection.execute(
            "SELECT repository_id FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"unknown snapshot: {snapshot_id}")

        self._connection.execute(
            "UPDATE snapshots SET state = ?"
            " WHERE repository_id = ? AND state = ? AND snapshot_id <> ?",
            (
                SnapshotState.SUPERSEDED.value,
                row["repository_id"],
                SnapshotState.ACTIVE.value,
                snapshot_id,
            ),
        )
        self._connection.execute(
            "UPDATE snapshots SET state = ?, activated_at = ? WHERE snapshot_id = ?",
            (SnapshotState.ACTIVE.value, to_utc_text(activated_at), snapshot_id),
        )

    def get(self, snapshot_id: str) -> Snapshot | None:
        row = self._connection.execute(
            "SELECT * FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def get_active(self, repository_id: str) -> Snapshot | None:
        row = self._connection.execute(
            "SELECT * FROM snapshots WHERE repository_id = ? AND state = ?",
            (repository_id, SnapshotState.ACTIVE.value),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def most_recent_superseded(self, repository_id: str) -> Snapshot | None:
        """Return the newest superseded snapshot, the rollback target."""
        row = self._connection.execute(
            "SELECT * FROM snapshots WHERE repository_id = ? AND state = ?"
            " ORDER BY activated_at DESC, created_at DESC, snapshot_id DESC"
            " LIMIT 1",
            (repository_id, SnapshotState.SUPERSEDED.value),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def rollback(self, repository_id: str, activated_at: datetime) -> str:
        """Demote the active snapshot and promote the newest superseded one.

        The caller wraps this in a write transaction. Order matters: the current
        active snapshot is demoted first so the partial unique index never sees
        two active rows, which is what makes the swap safe rather than merely
        usually correct.
        """
        target = self.most_recent_superseded(repository_id)
        if target is None:
            raise LookupError(f"no rollback target for {repository_id}")

        self._connection.execute(
            "UPDATE snapshots SET state = ?"
            " WHERE repository_id = ? AND state = ?",
            (
                SnapshotState.SUPERSEDED.value,
                repository_id,
                SnapshotState.ACTIVE.value,
            ),
        )
        self._connection.execute(
            "UPDATE snapshots SET state = ?, activated_at = ? WHERE snapshot_id = ?",
            (
                SnapshotState.ACTIVE.value,
                to_utc_text(activated_at),
                target.snapshot_id,
            ),
        )
        return target.snapshot_id

    def list_for_repository(self, repository_id: str) -> tuple[Snapshot, ...]:
        rows = self._connection.execute(
            "SELECT * FROM snapshots WHERE repository_id = ?"
            " ORDER BY created_at DESC, snapshot_id DESC",
            (repository_id,),
        ).fetchall()
        return tuple(_snapshot_from_row(row) for row in rows)

    def list_by_states(
        self,
        states: Sequence[SnapshotState],
        repository_id: str | None = None,
    ) -> tuple[Snapshot, ...]:
        placeholders = ", ".join("?" for _ in states)
        parameters: list[str] = [state.value for state in states]
        clause = f"state IN ({placeholders})"
        if repository_id is not None:
            clause += " AND repository_id = ?"
            parameters.append(repository_id)
        rows = self._connection.execute(
            f"SELECT * FROM snapshots WHERE {clause}"
            " ORDER BY created_at DESC, snapshot_id DESC",
            tuple(parameters),
        ).fetchall()
        return tuple(_snapshot_from_row(row) for row in rows)

    def delete(self, snapshot_id: str) -> None:
        """Delete a snapshot; foreign keys cascade to its derived rows."""
        self._connection.execute(
            "DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        )


class FileStore:
    """Files admitted into a snapshot."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_many(self, snapshot_id: str, files: Sequence[FileRecord]) -> None:
        self._connection.executemany(
            "INSERT INTO files ("
            " snapshot_id, file_id, relative_path, display_path, content_hash,"
            " size_bytes, line_count, language, classification"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    snapshot_id,
                    record.file_id,
                    record.relative_path,
                    record.display_path,
                    record.content_hash,
                    record.size_bytes,
                    record.line_count,
                    record.language,
                    record.classification.value,
                )
                for record in files
            ],
        )

    def list_for_snapshot(self, snapshot_id: str) -> tuple[FileRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM files WHERE snapshot_id = ? ORDER BY relative_path",
            (snapshot_id,),
        ).fetchall()
        return tuple(_file_from_row(row) for row in rows)

    def get(self, snapshot_id: str, file_id: str) -> FileRecord | None:
        row = self._connection.execute(
            "SELECT * FROM files WHERE snapshot_id = ? AND file_id = ?",
            (snapshot_id, file_id),
        ).fetchone()
        return _file_from_row(row) if row is not None else None


class SymbolStore:
    """Symbols extracted from a snapshot's files."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_many(self, snapshot_id: str, symbols: Sequence[SymbolRecord]) -> None:
        self._connection.executemany(
            "INSERT INTO symbols ("
            " snapshot_id, symbol_id, symbol_version_id, file_id, kind, name,"
            " qualified_name, module_path, signature, start_line, end_line,"
            " start_byte, end_byte, content_hash, visibility"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    snapshot_id,
                    record.symbol_id,
                    record.symbol_version_id,
                    record.file_id,
                    record.kind.value,
                    record.name,
                    record.qualified_name,
                    record.module_path,
                    record.signature,
                    record.start_line,
                    record.end_line,
                    record.start_byte,
                    record.end_byte,
                    record.content_hash,
                    record.visibility,
                )
                for record in symbols
            ],
        )

    def find_exact(
        self, snapshot_id: str, query: str, limit: int
    ) -> tuple[SymbolRecord, ...]:
        """Resolve a symbol by exact identity, most specific match first.

        Tiers are tried in order and the first non-empty tier wins, so an exact
        qualified-name match is never diluted by looser name matches.
        """
        tiers = (
            ("qualified_name = ?", (query,)),
            ("module_path || '.' || qualified_name = ?", (query,)),
            ("name = ?", (query,)),
            ("LOWER(name) = LOWER(?)", (query,)),
        )
        for predicate, parameters in tiers:
            rows = self._connection.execute(
                "SELECT symbols.* FROM symbols"
                " JOIN files ON files.snapshot_id = symbols.snapshot_id"
                "   AND files.file_id = symbols.file_id"
                f" WHERE symbols.snapshot_id = ? AND {predicate}"
                " ORDER BY files.relative_path, symbols.start_line"
                " LIMIT ?",
                (snapshot_id, *parameters, limit),
            ).fetchall()
            if rows:
                return tuple(_symbol_from_row(row) for row in rows)
        return ()

    def list_for_snapshot(self, snapshot_id: str) -> tuple[SymbolRecord, ...]:
        """Every symbol a snapshot holds, in stable file-then-position order.

        Resolution needs the whole set at once, because deciding what a name
        means is exactly the question a per-file view cannot answer.
        """
        rows = self._connection.execute(
            "SELECT symbols.* FROM symbols"
            " JOIN files ON files.snapshot_id = symbols.snapshot_id"
            "   AND files.file_id = symbols.file_id"
            " WHERE symbols.snapshot_id = ?"
            " ORDER BY files.relative_path, symbols.start_line, symbols.symbol_id",
            (snapshot_id,),
        ).fetchall()
        return tuple(_symbol_from_row(row) for row in rows)

    def copy_from_snapshot(
        self,
        source_snapshot_id: str,
        target_snapshot_id: str,
        file_ids: Sequence[str],
    ) -> int:
        """Copy unchanged files' symbols into a new snapshot; return the count."""
        if not file_ids:
            return 0
        placeholders = ", ".join("?" for _ in file_ids)
        cursor = self._connection.execute(
            "INSERT INTO symbols ("
            " snapshot_id, symbol_id, symbol_version_id, file_id, kind, name,"
            " qualified_name, module_path, signature, start_line, end_line,"
            " start_byte, end_byte, content_hash, visibility"
            ") SELECT ?, symbol_id, symbol_version_id, file_id, kind, name,"
            " qualified_name, module_path, signature, start_line, end_line,"
            " start_byte, end_byte, content_hash, visibility"
            " FROM symbols WHERE snapshot_id = ?"
            f" AND file_id IN ({placeholders})",
            (target_snapshot_id, source_snapshot_id, *file_ids),
        )
        return int(cursor.rowcount)

    def count_for_snapshot(self, snapshot_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM symbols WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return int(row[0])

    def invalid_line_ranges(self, snapshot_id: str) -> tuple[str, ...]:
        """Return symbol IDs whose line range is impossible for their file."""
        rows = self._connection.execute(
            "SELECT symbols.symbol_id FROM symbols"
            " JOIN files ON files.snapshot_id = symbols.snapshot_id"
            "   AND files.file_id = symbols.file_id"
            " WHERE symbols.snapshot_id = ?"
            "   AND (symbols.start_line < 1"
            "        OR symbols.end_line < symbols.start_line"
            "        OR symbols.end_line > files.line_count)",
            (snapshot_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)


class ChunkStore:
    """Retrieval chunks and the membership that makes them authoritative.

    Every write touches both tables together. `chunks` holds the rows;
    `snapshot_chunk_membership` declares which of them a snapshot actually
    contains. Keeping the two in step in one place is what lets validation treat
    a count mismatch as a real defect rather than an expected skew.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_many(self, snapshot_id: str, chunks: Sequence[LogicalChunk]) -> None:
        self._connection.executemany(
            "INSERT INTO chunks ("
            " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
            " role, qualified_name, heading_path, start_line, end_line,"
            " content_hash, retrieval_text, part_index, part_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    snapshot_id,
                    chunk.logical_chunk_id,
                    chunk.chunk_version_id,
                    chunk.file_id,
                    chunk.symbol_id,
                    chunk.role.value,
                    chunk.qualified_name,
                    chunk.heading_path,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.content_hash,
                    chunk.retrieval_text,
                    chunk.part_index,
                    chunk.part_count,
                )
                for chunk in chunks
            ],
        )
        self._connection.executemany(
            "INSERT INTO snapshot_chunk_membership ("
            " snapshot_id, logical_chunk_id, chunk_version_id, part_index"
            ") VALUES (?, ?, ?, ?)",
            [
                (
                    snapshot_id,
                    chunk.logical_chunk_id,
                    chunk.chunk_version_id,
                    chunk.part_index,
                )
                for chunk in chunks
            ],
        )

    def list_for_snapshot(self, snapshot_id: str) -> tuple[LogicalChunk, ...]:
        rows = self._connection.execute(
            f"{_CHUNK_SELECT} WHERE chunks.snapshot_id = ? {_CHUNK_ORDER}",
            (snapshot_id,),
        ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def list_for_file(
        self, snapshot_id: str, file_id: str
    ) -> tuple[LogicalChunk, ...]:
        rows = self._connection.execute(
            f"{_CHUNK_SELECT} WHERE chunks.snapshot_id = ? AND chunks.file_id = ?"
            f" {_CHUNK_ORDER}",
            (snapshot_id, file_id),
        ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def copy_from_snapshot(
        self,
        source_snapshot_id: str,
        target_snapshot_id: str,
        file_ids: Sequence[str],
    ) -> int:
        """Copy unchanged files' chunks into a new snapshot; return the count.

        The returned count is the phase's reuse evidence, so it reports rows
        actually written rather than rows requested.
        """
        if not file_ids:
            return 0

        placeholders = ", ".join("?" for _ in file_ids)
        parameters = (target_snapshot_id, source_snapshot_id, *file_ids)
        cursor = self._connection.execute(
            "INSERT INTO chunks ("
            " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
            " role, qualified_name, heading_path, start_line, end_line,"
            " content_hash, retrieval_text, part_index, part_count"
            ") SELECT ?, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
            " role, qualified_name, heading_path, start_line, end_line,"
            " content_hash, retrieval_text, part_index, part_count"
            " FROM chunks WHERE snapshot_id = ?"
            f" AND file_id IN ({placeholders})",
            parameters,
        )
        copied = int(cursor.rowcount)

        self._connection.execute(
            "INSERT INTO snapshot_chunk_membership ("
            " snapshot_id, logical_chunk_id, chunk_version_id, part_index"
            ") SELECT ?, logical_chunk_id, chunk_version_id, part_index"
            " FROM chunks WHERE snapshot_id = ?"
            f" AND file_id IN ({placeholders})",
            parameters,
        )
        return copied

    def count_for_snapshot(self, snapshot_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return int(row[0])

    def count_membership(self, snapshot_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM snapshot_chunk_membership WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return int(row[0])

    def invalid_line_ranges(self, snapshot_id: str) -> tuple[str, ...]:
        """Return chunk IDs whose line range is impossible for their file."""
        rows = self._connection.execute(
            "SELECT chunks.logical_chunk_id FROM chunks"
            " JOIN files ON files.snapshot_id = chunks.snapshot_id"
            "   AND files.file_id = chunks.file_id"
            " WHERE chunks.snapshot_id = ?"
            "   AND (chunks.start_line < 1"
            "        OR chunks.end_line < chunks.start_line"
            "        OR chunks.end_line > files.line_count)",
            (snapshot_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def orphan_membership(self, snapshot_id: str) -> tuple[str, ...]:
        """Return membership rows with no matching chunk in the same snapshot."""
        rows = self._connection.execute(
            "SELECT membership.logical_chunk_id FROM snapshot_chunk_membership"
            " AS membership"
            " LEFT JOIN chunks ON chunks.snapshot_id = membership.snapshot_id"
            "   AND chunks.logical_chunk_id = membership.logical_chunk_id"
            "   AND chunks.part_index = membership.part_index"
            " WHERE membership.snapshot_id = ? AND chunks.logical_chunk_id IS NULL",
            (snapshot_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)


class SearchStore:
    """The FTS5 projection of chunks and file paths.

    The projection is written explicitly rather than through an external-content
    FTS table. That costs a little duplication and buys the ability to compare
    projection row counts against chunk row counts directly, so a partially
    written index is a detectable condition instead of a silent one.

    A match expression must already have come through
    ``retrieval.fts_query.build_match_expression``. Nothing here re-validates it,
    and nothing here builds one from user text.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def index_chunks(
        self,
        snapshot_id: str,
        chunks: Sequence[LogicalChunk],
        paths_by_file_id: Mapping[str, str],
    ) -> None:
        self._connection.executemany(
            "INSERT INTO chunk_search ("
            " logical_chunk_id, part_index, snapshot_id, file_path, symbol_name,"
            " content"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    chunk.logical_chunk_id,
                    chunk.part_index,
                    snapshot_id,
                    paths_by_file_id.get(chunk.file_id, ""),
                    chunk.qualified_name,
                    chunk.retrieval_text,
                )
                for chunk in chunks
            ],
        )

    def index_files(self, snapshot_id: str, files: Sequence[FileRecord]) -> None:
        self._connection.executemany(
            "INSERT INTO file_search (file_id, snapshot_id, file_path)"
            " VALUES (?, ?, ?)",
            [(record.file_id, snapshot_id, record.relative_path) for record in files],
        )

    def delete_for_snapshot(self, snapshot_id: str) -> None:
        self._connection.execute(
            "DELETE FROM chunk_search WHERE snapshot_id = ?", (snapshot_id,)
        )
        self._connection.execute(
            "DELETE FROM file_search WHERE snapshot_id = ?", (snapshot_id,)
        )

    def search_chunks(
        self,
        snapshot_id: str,
        match_expression: str,
        limit: int,
        column: str | None = None,
    ) -> tuple[ChunkSearchHit, ...]:
        """Search chunks, optionally restricted to one indexed column.

        ``column`` is checked against a fixed set rather than trusted, because a
        column filter is FTS syntax and the only safe source of FTS syntax is
        this codebase.
        """
        if column is not None:
            if column not in _SEARCHABLE_CHUNK_COLUMNS:
                raise ValueError(f"unknown search column: {column!r}")
            match_expression = f"{column} : ({match_expression})"

        rows = self._connection.execute(
            "SELECT chunks.logical_chunk_id, chunks.part_index, chunks.file_id,"
            "       files.relative_path, chunks.qualified_name, chunks.role,"
            "       chunks.symbol_id, chunks.start_line, chunks.end_line,"
            "       bm25(chunk_search) AS rank"
            " FROM chunk_search"
            " JOIN chunks ON chunks.snapshot_id = chunk_search.snapshot_id"
            "   AND chunks.logical_chunk_id = chunk_search.logical_chunk_id"
            "   AND chunks.part_index = chunk_search.part_index"
            " JOIN files ON files.snapshot_id = chunks.snapshot_id"
            "   AND files.file_id = chunks.file_id"
            " WHERE chunk_search MATCH ? AND chunk_search.snapshot_id = ?"
            " ORDER BY rank, files.relative_path, chunks.start_line,"
            "          chunks.part_index"
            " LIMIT ?",
            (match_expression, snapshot_id, limit),
        ).fetchall()
        return tuple(
            ChunkSearchHit(
                logical_chunk_id=row["logical_chunk_id"],
                part_index=int(row["part_index"]),
                file_id=row["file_id"],
                relative_path=row["relative_path"],
                qualified_name=row["qualified_name"],
                role=ChunkRole(row["role"]),
                symbol_id=row["symbol_id"],
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                rank=float(row["rank"]),
            )
            for row in rows
        )

    def search_files(
        self, snapshot_id: str, match_expression: str, limit: int
    ) -> tuple[FileSearchHit, ...]:
        rows = self._connection.execute(
            "SELECT file_search.file_id, files.relative_path,"
            "       bm25(file_search) AS rank"
            " FROM file_search"
            " JOIN files ON files.snapshot_id = file_search.snapshot_id"
            "   AND files.file_id = file_search.file_id"
            " WHERE file_search MATCH ? AND file_search.snapshot_id = ?"
            " ORDER BY rank, files.relative_path"
            " LIMIT ?",
            (match_expression, snapshot_id, limit),
        ).fetchall()
        return tuple(
            FileSearchHit(
                file_id=row["file_id"],
                relative_path=row["relative_path"],
                rank=float(row["rank"]),
            )
            for row in rows
        )

    def copy_from_snapshot(
        self,
        source_snapshot_id: str,
        target_snapshot_id: str,
        file_ids: Sequence[str],
    ) -> int:
        """Copy an unchanged file's projection rows into a new snapshot.

        The projection is copied rather than rebuilt for the same reason the
        chunks are: re-tokenizing text that did not change is work whose only
        possible outcome is the same rows.
        """
        if not file_ids:
            return 0
        placeholders = ", ".join("?" for _ in file_ids)
        cursor = self._connection.execute(
            "INSERT INTO chunk_search ("
            " logical_chunk_id, part_index, snapshot_id, file_path, symbol_name,"
            " content"
            ") SELECT logical_chunk_id, part_index, ?, file_path, symbol_name,"
            " content"
            " FROM chunk_search WHERE snapshot_id = ?"
            f" AND logical_chunk_id IN ("
            "   SELECT logical_chunk_id FROM chunks WHERE snapshot_id = ?"
            f"   AND file_id IN ({placeholders})"
            " )",
            (
                target_snapshot_id,
                source_snapshot_id,
                source_snapshot_id,
                *file_ids,
            ),
        )
        return int(cursor.rowcount)

    def count_indexed(self, snapshot_id: str) -> tuple[int, int]:
        """Return ``(chunk_rows, projection_rows)`` for the snapshot.

        Validation compares these before activation: a projection that does not
        cover every chunk means an interrupted write, and an interrupted write
        must never become the active snapshot.
        """
        chunk_rows = self._connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()[0]
        projection_rows = self._connection.execute(
            "SELECT COUNT(*) FROM chunk_search WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()[0]
        return int(chunk_rows), int(projection_rows)


class IndexJobStore:
    """Indexing job lifecycle records."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection = connection
        self._clock = clock or (lambda: datetime.now(UTC))

    def start(self, job_id: str, repository_id: str, snapshot_id: str) -> None:
        now = to_utc_text(self._clock())
        self._connection.execute(
            "INSERT INTO index_jobs ("
            " job_id, repository_id, snapshot_id, stage, status, attempts,"
            " started_at, updated_at, diagnostics"
            ") VALUES (?, ?, ?, 'scanning', 'running', 1, ?, ?, '[]')",
            (job_id, repository_id, snapshot_id, now, now),
        )

    def update_stage(self, job_id: str, stage: str, status: str) -> None:
        self._connection.execute(
            "UPDATE index_jobs SET stage = ?, status = ?, updated_at = ?"
            " WHERE job_id = ?",
            (stage, status, to_utc_text(self._clock()), job_id),
        )

    def set_snapshot(self, job_id: str, snapshot_id: str) -> None:
        self._connection.execute(
            "UPDATE index_jobs SET snapshot_id = ?, updated_at = ? WHERE job_id = ?",
            (snapshot_id, to_utc_text(self._clock()), job_id),
        )

    def finish(
        self,
        job_id: str,
        status: str,
        diagnostics: Mapping[str, Any],
    ) -> None:
        """Close a job, storing bounded structured diagnostics as JSON.

        Diagnostics describe the run that produced the snapshot, so a later
        status query can explain what was skipped without re-scanning.
        """
        self._connection.execute(
            "UPDATE index_jobs SET status = ?, updated_at = ?, diagnostics = ?"
            " WHERE job_id = ?",
            (
                status,
                to_utc_text(self._clock()),
                json.dumps(dict(diagnostics), sort_keys=True),
                job_id,
            ),
        )

    def latest_for(self, repository_id: str) -> Mapping[str, Any] | None:
        """Return the most recent job's diagnostics for a repository."""
        row = self._connection.execute(
            "SELECT diagnostics FROM index_jobs"
            " WHERE repository_id = ? ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (repository_id,),
        ).fetchone()
        if row is None:
            return None
        parsed = json.loads(row["diagnostics"])
        return parsed if isinstance(parsed, dict) else None

    def active_job_for(self, repository_id: str) -> str | None:
        placeholders = ", ".join("?" for _ in _ACTIVE_JOB_STATUSES)
        row = self._connection.execute(
            "SELECT job_id FROM index_jobs"
            f" WHERE repository_id = ? AND status IN ({placeholders})"
            " ORDER BY started_at DESC LIMIT 1",
            (repository_id, *_ACTIVE_JOB_STATUSES),
        ).fetchone()
        return str(row[0]) if row is not None else None


def _repository_from_row(row: sqlite3.Row) -> Repository:
    return Repository(
        repository_id=row["repository_id"],
        display_name=row["display_name"],
        canonical_root=row["canonical_root"],
        created_at=from_utc_text(row["created_at"]),
        watch_enabled=bool(row["watch_enabled"]),
    )


def _snapshot_from_row(row: sqlite3.Row) -> Snapshot:
    activated_at = row["activated_at"]
    return Snapshot(
        snapshot_id=row["snapshot_id"],
        repository_id=row["repository_id"],
        state=SnapshotState(row["state"]),
        git_head=row["git_head"],
        git_branch=row["git_branch"],
        git_dirty=bool(row["git_dirty"]),
        working_tree_fingerprint=row["working_tree_fingerprint"],
        file_count=int(row["file_count"]),
        parsed_file_count=int(row["parsed_file_count"]),
        skipped_file_count=int(row["skipped_file_count"]),
        parse_error_count=int(row["parse_error_count"]),
        parser_bundle_version=row["parser_bundle_version"],
        index_version=row["index_version"],
        created_at=from_utc_text(row["created_at"]),
        activated_at=from_utc_text(activated_at) if activated_at else None,
        chunker_version=row["chunker_version"],
        resolver_version=row["resolver_version"],
    )


def _file_from_row(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        file_id=row["file_id"],
        relative_path=row["relative_path"],
        display_path=row["display_path"],
        content_hash=row["content_hash"],
        size_bytes=int(row["size_bytes"]),
        line_count=int(row["line_count"]),
        language=row["language"],
        classification=FileClassification(row["classification"]),
    )


def _chunk_from_row(row: sqlite3.Row) -> LogicalChunk:
    return LogicalChunk(
        logical_chunk_id=row["logical_chunk_id"],
        chunk_version_id=row["chunk_version_id"],
        file_id=row["file_id"],
        symbol_id=row["symbol_id"],
        role=ChunkRole(row["role"]),
        qualified_name=row["qualified_name"],
        heading_path=row["heading_path"],
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        content_hash=row["content_hash"],
        retrieval_text=row["retrieval_text"],
        part_index=int(row["part_index"]),
        part_count=int(row["part_count"]),
    )


class RelationStore:
    """Resolved edges between symbols, scoped to one snapshot.

    ``outgoing`` and ``incoming`` take a *sequence* of symbol IDs so traversal
    expands a whole frontier in one statement. A per-node query would be the N+1
    pattern ``CLAUDE.md`` Section 10.3 forbids, and traversal is the hottest path
    in this phase.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_many(
        self, snapshot_id: str, relations: Sequence[RelationRecord]
    ) -> None:
        self._connection.executemany(
            "INSERT INTO relations ("
            " snapshot_id, relation_id, source_symbol_id, target_symbol_id,"
            " file_id, kind, target_hint, resolution, derivation, confidence,"
            " start_line, end_line, candidate_count, module_hint, reference_part"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    snapshot_id,
                    relation.relation_id,
                    relation.source_symbol_id,
                    relation.target_symbol_id,
                    relation.file_id,
                    relation.kind.value,
                    relation.target_hint,
                    relation.resolution.value,
                    relation.derivation.value,
                    relation.confidence,
                    relation.start_line,
                    relation.end_line,
                    relation.candidate_count,
                    relation.module_hint,
                    relation.reference_part,
                )
                for relation in relations
            ],
        )

    def list_for_snapshot(self, snapshot_id: str) -> tuple[RelationRecord, ...]:
        rows = self._connection.execute(
            f"SELECT * FROM relations WHERE snapshot_id = ? {_RELATION_ORDER}",
            (snapshot_id,),
        ).fetchall()
        return tuple(_relation_from_row(row) for row in rows)

    def list_for_file(
        self, snapshot_id: str, file_id: str
    ) -> tuple[RelationRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM relations WHERE snapshot_id = ? AND file_id = ?"
            f" {_RELATION_ORDER}",
            (snapshot_id, file_id),
        ).fetchall()
        return tuple(_relation_from_row(row) for row in rows)

    def outgoing(
        self,
        snapshot_id: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        """Edges leaving any of ``symbol_ids`` — callees, imports, bases."""
        return self._frontier(snapshot_id, "source_symbol_id", symbol_ids, kinds)

    def incoming(
        self,
        snapshot_id: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        """Edges arriving at any of ``symbol_ids`` — callers, dependents."""
        return self._frontier(snapshot_id, "target_symbol_id", symbol_ids, kinds)

    def count_for_snapshot(self, snapshot_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM relations WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return int(row[0])

    def dangling_endpoints(self, snapshot_id: str) -> tuple[str, ...]:
        """Return IDs of relations whose source or resolved target is absent.

        A NULL ``target_symbol_id`` is *not* dangling: it means no repository
        symbol answers the reference, which is a valid recorded state. Only a
        target that claims to name a symbol, and does not, is a defect.

        Returns relation IDs rather than symbol IDs so a validation failure names
        the row to inspect, matching ``ChunkStore.invalid_line_ranges``.
        """
        rows = self._connection.execute(
            "SELECT relation_id FROM relations AS r"
            " WHERE r.snapshot_id = ?"
            "   AND ("
            "     NOT EXISTS ("
            "       SELECT 1 FROM symbols AS s"
            "       WHERE s.snapshot_id = r.snapshot_id"
            "         AND s.symbol_id = r.source_symbol_id"
            "     )"
            "     OR ("
            "       r.target_symbol_id IS NOT NULL"
            "       AND NOT EXISTS ("
            "         SELECT 1 FROM symbols AS s"
            "         WHERE s.snapshot_id = r.snapshot_id"
            "           AND s.symbol_id = r.target_symbol_id"
            "       )"
            "     )"
            "   )"
            " ORDER BY relation_id",
            (snapshot_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def invalid_line_ranges(self, snapshot_id: str) -> tuple[str, ...]:
        """Return IDs of relations citing a line their file does not have.

        An edge with no citable site is not evidence, so this is checked before
        activation rather than discovered when a reader clicks a citation.
        """
        rows = self._connection.execute(
            "SELECT relations.relation_id FROM relations"
            " JOIN files ON files.snapshot_id = relations.snapshot_id"
            "   AND files.file_id = relations.file_id"
            " WHERE relations.snapshot_id = ?"
            "   AND (relations.start_line < 1"
            "     OR relations.end_line < relations.start_line"
            "     OR relations.end_line > files.line_count)"
            " ORDER BY relations.relation_id",
            (snapshot_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def delete_for_snapshot(self, snapshot_id: str) -> None:
        self._connection.execute(
            "DELETE FROM relations WHERE snapshot_id = ?", (snapshot_id,)
        )

    def _frontier(
        self,
        snapshot_id: str,
        column: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None,
    ) -> tuple[RelationRecord, ...]:
        if not symbol_ids:
            return ()

        # `column` is chosen by this class, never by a caller, so the two
        # literal names below are the only values it can ever hold.
        symbol_placeholders = ", ".join("?" for _ in symbol_ids)
        sql = (
            f"SELECT * FROM relations WHERE snapshot_id = ?"
            f" AND {column} IN ({symbol_placeholders})"
        )
        parameters: list[Any] = [snapshot_id, *symbol_ids]
        if kinds:
            kind_placeholders = ", ".join("?" for _ in kinds)
            sql += f" AND kind IN ({kind_placeholders})"
            parameters.extend(kind.value for kind in kinds)
        rows = self._connection.execute(
            f"{sql} {_RELATION_ORDER}", parameters
        ).fetchall()
        return tuple(_relation_from_row(row) for row in rows)


class EvidenceStore:
    """Addressable evidence: identity, location, and hash — never the excerpt.

    Evidence IDs are content-derived hashes and are not reversible, so serving
    `GET /v1/evidence/{id}` needs them persisted. What is *not* persisted matters
    just as much: the excerpt is re-read from disk and re-verified on every
    fetch, so a stored row can never become a second, staler source of truth
    about a file's contents.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_many(
        self, snapshot_id: str, records: Sequence[StoredEvidence]
    ) -> None:
        self._connection.executemany(
            "INSERT INTO evidence ("
            " snapshot_id, evidence_id, file_id, start_line, end_line,"
            " content_hash, derivation"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(snapshot_id, evidence_id) DO NOTHING",
            [
                (
                    snapshot_id,
                    record.evidence_id,
                    record.file_id,
                    record.start_line,
                    record.end_line,
                    record.content_hash,
                    record.derivation.value,
                )
                for record in records
            ],
        )

    def get(self, snapshot_id: str, evidence_id: str) -> StoredEvidence | None:
        row = self._connection.execute(
            "SELECT * FROM evidence WHERE snapshot_id = ? AND evidence_id = ?",
            (snapshot_id, evidence_id),
        ).fetchone()
        if row is None:
            return None
        return StoredEvidence(
            evidence_id=row["evidence_id"],
            file_id=row["file_id"],
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            content_hash=row["content_hash"],
            derivation=Derivation(row["derivation"]),
        )

    def count_for_snapshot(self, snapshot_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM evidence WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return int(row[0])


def _relation_from_row(row: sqlite3.Row) -> RelationRecord:
    return RelationRecord(
        relation_id=row["relation_id"],
        source_symbol_id=row["source_symbol_id"],
        target_symbol_id=row["target_symbol_id"],
        file_id=row["file_id"],
        kind=RelationKind(row["kind"]),
        target_hint=row["target_hint"],
        resolution=ResolutionState(row["resolution"]),
        derivation=Derivation(row["derivation"]),
        confidence=float(row["confidence"]),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        candidate_count=int(row["candidate_count"]),
        module_hint=row["module_hint"],
        reference_part=int(row["reference_part"]),
    )


def _symbol_from_row(row: sqlite3.Row) -> SymbolRecord:
    visibility: Visibility = "private" if row["visibility"] == "private" else "public"
    return SymbolRecord(
        symbol_id=row["symbol_id"],
        symbol_version_id=row["symbol_version_id"],
        file_id=row["file_id"],
        kind=SymbolKind(row["kind"]),
        name=row["name"],
        qualified_name=row["qualified_name"],
        module_path=row["module_path"],
        signature=row["signature"],
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        start_byte=int(row["start_byte"]),
        end_byte=int(row["end_byte"]),
        content_hash=row["content_hash"],
        visibility=visibility,
    )


class ChangeAnalysisStore:
    """Persisted change analyses, kept as audit records rather than as a cache.

    An analysis outlives the snapshot it examined. "What did CodeAtlas say about
    this change, and on what evidence" has to stay answerable after the tree has
    moved on, so nothing here is keyed to snapshot lifetime; the target snapshot
    ID is carried as a plain value for provenance.

    The report is stored decomposed — findings and evidence in their own tables,
    the rest as bounded JSON columns — so a finding can be read back by rank
    without rehydrating a whole document, while the parts with no query pattern
    of their own stay in one place.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, report: ChangeAnalysisReport) -> None:
        """Write one analysis and everything it cites, replacing any prior row."""
        self._connection.execute(
            "DELETE FROM change_analyses WHERE analysis_id = ?",
            (report.analysis_id,),
        )
        self._connection.execute(
            "INSERT INTO change_analyses ("
            " analysis_id, repository_id, kind, status, overall_risk,"
            " base_ref, target_ref, base_commit, target_commit,"
            " target_snapshot_id, changed_file_count, changed_symbol_count,"
            " finding_count, changed_files_json, impact_edges_json,"
            " test_gaps_json, warnings_json, limitations_json, timing_json,"
            " created_at, completed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.analysis_id,
                report.repository_id,
                report.kind.value,
                report.status.value,
                report.overall_risk.value,
                report.base.ref,
                report.target.ref,
                report.base.commit,
                report.target.commit,
                report.target.snapshot_id,
                len(report.changed_files),
                len(report.changed_symbols),
                len(report.findings),
                _dump_models(report.changed_files),
                _dump_models(report.impact_edges),
                json.dumps(list(report.test_gaps)),
                json.dumps(list(report.warnings)),
                json.dumps(list(report.limitations)),
                json.dumps(dict(report.timing_ms)),
                to_utc_text(report.created_at),
                to_utc_text(report.completed_at) if report.completed_at else None,
            ),
        )
        self._connection.executemany(
            "INSERT INTO change_changed_symbols ("
            " analysis_id, ordinal, qualified_name, symbol_kind, change_kind,"
            " file_path, base_file_path, base_start_line, base_end_line,"
            " target_start_line, target_end_line, signature_changed, public,"
            " derivation, confidence"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    report.analysis_id,
                    ordinal,
                    item.qualified_name,
                    item.symbol_kind.value,
                    item.change_kind.value,
                    item.file_path,
                    item.base_file_path,
                    item.base_start_line,
                    item.base_end_line,
                    item.target_start_line,
                    item.target_end_line,
                    int(item.signature_changed),
                    int(item.public),
                    item.derivation.value,
                    item.confidence,
                )
                for ordinal, item in enumerate(report.changed_symbols)
            ],
        )
        self._connection.executemany(
            "INSERT INTO change_findings ("
            " analysis_id, finding_id, rank, code, severity, title, description,"
            " derivation, confidence, evidence_ids_json, remediation,"
            " limitations_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    report.analysis_id,
                    f"{report.analysis_id}_f{rank}",
                    rank,
                    item.code,
                    item.severity.value,
                    item.title,
                    item.description,
                    item.derivation.value,
                    item.confidence,
                    json.dumps(list(item.evidence_ids)),
                    item.remediation,
                    json.dumps(list(item.limitations)),
                )
                for rank, item in enumerate(report.findings)
            ],
        )
        self._connection.executemany(
            "INSERT INTO change_evidence ("
            " analysis_id, evidence_id, side, file_path, symbol, start_line,"
            " end_line, content_hash, derivation, confidence"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    report.analysis_id,
                    item.evidence_id,
                    item.side.value,
                    item.file_path,
                    item.symbol,
                    item.start_line,
                    item.end_line,
                    item.content_hash,
                    item.derivation.value,
                    item.confidence,
                )
                for item in report.evidence
            ],
        )

    def get(self, analysis_id: str) -> ChangeAnalysisReport | None:
        """Read one analysis back exactly as it was written, or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM change_analyses WHERE analysis_id = ?",
            (analysis_id,),
        ).fetchone()
        if row is None:
            return None
        return ChangeAnalysisReport(
            analysis_id=row["analysis_id"],
            request_id=row["analysis_id"],
            repository_id=row["repository_id"],
            kind=ChangeAnalysisKind(row["kind"]),
            status=ChangeAnalysisStatus(row["status"]),
            overall_risk=OverallRisk(row["overall_risk"]),
            base=AnalysisStateRef(
                ref=row["base_ref"],
                commit=row["base_commit"],
                snapshot_id=None,
                freshness=SnapshotFreshness.STALE,
            ),
            target=AnalysisStateRef(
                ref=row["target_ref"],
                commit=row["target_commit"],
                snapshot_id=row["target_snapshot_id"],
                freshness=SnapshotFreshness.FRESH,
            ),
            changed_files=[
                ChangedFile.model_validate(item)
                for item in json.loads(row["changed_files_json"])
            ],
            changed_symbols=self._changed_symbols(analysis_id),
            impact_edges=[
                ContractImpactEdge.model_validate(item)
                for item in json.loads(row["impact_edges_json"])
            ],
            findings=self._findings(analysis_id),
            evidence=self._evidence(analysis_id),
            test_gaps=json.loads(row["test_gaps_json"]),
            warnings=json.loads(row["warnings_json"]),
            limitations=json.loads(row["limitations_json"]),
            timing_ms=json.loads(row["timing_json"]),
            created_at=from_utc_text(row["created_at"]),
            completed_at=(
                from_utc_text(row["completed_at"])
                if row["completed_at"]
                else None
            ),
        )

    def list_for_repository(
        self, repository_id: str, limit: int = 50
    ) -> tuple[str, ...]:
        """Analysis IDs for one repository, newest first."""
        rows = self._connection.execute(
            "SELECT analysis_id FROM change_analyses"
            " WHERE repository_id = ?"
            " ORDER BY created_at DESC, analysis_id"
            " LIMIT ?",
            (repository_id, limit),
        ).fetchall()
        return tuple(row["analysis_id"] for row in rows)

    def _changed_symbols(self, analysis_id: str) -> list[ChangedSymbol]:
        rows = self._connection.execute(
            "SELECT * FROM change_changed_symbols"
            " WHERE analysis_id = ? ORDER BY ordinal",
            (analysis_id,),
        ).fetchall()
        return [
            ChangedSymbol(
                qualified_name=row["qualified_name"],
                symbol_kind=SymbolKind(row["symbol_kind"]),
                change_kind=ChangeKind(row["change_kind"]),
                file_path=row["file_path"],
                base_file_path=row["base_file_path"],
                base_start_line=row["base_start_line"],
                base_end_line=row["base_end_line"],
                target_start_line=row["target_start_line"],
                target_end_line=row["target_end_line"],
                signature_changed=bool(row["signature_changed"]),
                public=bool(row["public"]),
                derivation=Derivation(row["derivation"]),
                confidence=row["confidence"],
            )
            for row in rows
        ]

    def _findings(self, analysis_id: str) -> list[Finding]:
        rows = self._connection.execute(
            "SELECT * FROM change_findings WHERE analysis_id = ? ORDER BY rank",
            (analysis_id,),
        ).fetchall()
        return [
            Finding(
                code=row["code"],
                severity=Severity(row["severity"]),
                title=row["title"],
                description=row["description"],
                derivation=Derivation(row["derivation"]),
                confidence=row["confidence"],
                evidence_ids=json.loads(row["evidence_ids_json"]),
                remediation=row["remediation"],
                limitations=json.loads(row["limitations_json"]),
            )
            for row in rows
        ]

    def _evidence(self, analysis_id: str) -> list[ChangeEvidenceItem]:
        rows = self._connection.execute(
            "SELECT * FROM change_evidence"
            " WHERE analysis_id = ? ORDER BY evidence_id",
            (analysis_id,),
        ).fetchall()
        return [
            ChangeEvidenceItem(
                evidence_id=row["evidence_id"],
                side=AnalysisSide(row["side"]),
                file_path=row["file_path"],
                symbol=row["symbol"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                content_hash=row["content_hash"],
                derivation=Derivation(row["derivation"]),
                confidence=row["confidence"],
            )
            for row in rows
        ]


def _dump_models(items: Sequence[Any]) -> str:
    """Serialize contract models to the JSON stored in a bounded column."""
    return json.dumps([item.model_dump(mode="json") for item in items])


class ConversationStore:
    """Persisted chat history: conversations, messages, runs, and citations.

    Two rules drive the shape of this class.

    **A turn is one fact.** Creating a user message, its queued assistant
    message, and the run that will answer it happens in one transaction, as does
    completing an answer with its citations. A half-written turn would show a
    question with no answer coming, and answer text without its citations is
    exactly the uncited claim the evidence contract forbids. The caller supplies
    the transaction, because the application service usually has more to commit
    alongside.

    **History is a record, not a cache.** A retry adds a run rather than
    replacing one, deletion is soft, and evidence rows carry their own fields so
    a citation still says what it said after its snapshot is superseded.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    # -- conversations ----------------------------------------------------

    def create_conversation(self, record: ConversationRecord) -> None:
        self._connection.execute(
            "INSERT INTO conversations ("
            " conversation_id, repository_id, title, pinned_snapshot_policy,"
            " created_at, updated_at, last_message_at, archived_at, deleted_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.conversation_id,
                record.repository_id,
                record.title,
                record.pinned_snapshot_policy,
                to_utc_text(record.created_at),
                to_utc_text(record.updated_at),
                _optional_utc(record.last_message_at),
                _optional_utc(record.archived_at),
                _optional_utc(record.deleted_at),
            ),
        )

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        """Load one conversation, or ``None`` if it is absent or deleted.

        A soft-deleted row is *not found* here: deletion is a user-visible fact,
        and returning the row because it physically survives would contradict
        what the user was told.
        """
        row = self._connection.execute(
            "SELECT * FROM conversations"
            " WHERE conversation_id = ? AND deleted_at IS NULL",
            (conversation_id,),
        ).fetchone()
        return _conversation_from_row(row) if row is not None else None

    def list_conversations(
        self,
        repository_id: str,
        *,
        cursor: str | None,
        limit: int,
        include_archived: bool = False,
    ) -> Page[ConversationRecord]:
        """List a repository's conversations, newest activity first.

        The cursor carries the ordering key of the last row returned, so
        inserting a newer conversation cannot shift a page boundary and
        duplicate a row across pages.
        """
        clauses = ["repository_id = ?", "deleted_at IS NULL"]
        parameters: list[Any] = [repository_id]
        if not include_archived:
            clauses.append("archived_at IS NULL")
        if cursor is not None:
            clauses.append(
                "(COALESCE(last_message_at, created_at), conversation_id) < (?, ?)"
            )
            activity, _, identifier = cursor.partition("|")
            parameters.extend([activity, identifier])

        where = " AND ".join(clauses)
        rows = self._connection.execute(
            "SELECT * FROM conversations"
            f" WHERE {where}"
            " ORDER BY COALESCE(last_message_at, created_at) DESC,"
            " conversation_id DESC"
            " LIMIT ?",
            (*parameters, limit + 1),
        ).fetchall()

        items = [_conversation_from_row(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            activity_at = last.last_message_at or last.created_at
            next_cursor = f"{to_utc_text(activity_at)}|{last.conversation_id}"
        return Page(items=tuple(items), next_cursor=next_cursor)

    def rename(
        self, conversation_id: str, *, title: str, updated_at: datetime
    ) -> None:
        self._connection.execute(
            "UPDATE conversations SET title = ?, updated_at = ?"
            " WHERE conversation_id = ? AND deleted_at IS NULL",
            (title, to_utc_text(updated_at), conversation_id),
        )

    def archive(self, conversation_id: str, *, archived_at: datetime) -> None:
        self._connection.execute(
            "UPDATE conversations SET archived_at = ?, updated_at = ?"
            " WHERE conversation_id = ? AND deleted_at IS NULL",
            (to_utc_text(archived_at), to_utc_text(archived_at), conversation_id),
        )

    def soft_delete(self, conversation_id: str, *, deleted_at: datetime) -> None:
        """Hide a conversation while keeping it recoverable.

        Phase 6 defines retention and the purge path; until then a deletion is
        reversible, which is why the rows stay.
        """
        self._connection.execute(
            "UPDATE conversations SET deleted_at = ?, updated_at = ?"
            " WHERE conversation_id = ?",
            (to_utc_text(deleted_at), to_utc_text(deleted_at), conversation_id),
        )

    # -- messages and runs ------------------------------------------------

    def next_sequence_number(self, conversation_id: str) -> int:
        """The position the next message takes. Starts at 1."""
        row = self._connection.execute(
            "SELECT MAX(sequence_number) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        highest = row[0] if row is not None else None
        return int(highest) + 1 if highest is not None else 1

    def create_user_turn(
        self,
        user: MessageRecord,
        assistant: MessageRecord,
        run: RunRecord,
    ) -> None:
        """Insert the question, the pending answer, and its first run together."""
        self._insert_message(user)
        self._insert_message(assistant)
        self._insert_run(run)
        self._touch_conversation(user.conversation_id, user.created_at)

    def complete_assistant(
        self,
        *,
        message_id: str,
        content: str,
        evidence: Sequence[MessageEvidenceRow],
        run_id: str,
        latency_ms: float,
        completed_at: datetime,
    ) -> None:
        """Commit an answer and its citations as one fact."""
        _check_content_bound(content)
        self._connection.execute(
            "UPDATE messages SET status = ?, content = ?, completed_at = ?,"
            " error_code = NULL WHERE message_id = ?",
            (
                MessageStatus.COMPLETE.value,
                content,
                to_utc_text(completed_at),
                message_id,
            ),
        )
        self._connection.execute(
            "DELETE FROM message_evidence WHERE message_id = ?", (message_id,)
        )
        self._connection.executemany(
            "INSERT INTO message_evidence ("
            " message_id, citation_ordinal, evidence_id, file_path, symbol,"
            " start_line, end_line, content_hash, derivation, confidence,"
            " snapshot_id, claim_ids_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    message_id,
                    item.citation_ordinal,
                    item.evidence_id,
                    item.file_path,
                    item.symbol,
                    item.start_line,
                    item.end_line,
                    item.content_hash,
                    item.derivation.value,
                    item.confidence,
                    item.snapshot_id,
                    json.dumps(list(item.claim_ids)),
                )
                for item in evidence
            ],
        )
        self._connection.execute(
            "UPDATE message_runs SET status = ?, latency_ms = ?, completed_at = ?"
            " WHERE run_id = ?",
            (
                RunStatus.COMPLETE.value,
                latency_ms,
                to_utc_text(completed_at),
                run_id,
            ),
        )
        self._touch_message_conversation(message_id, completed_at)

    def fail_or_cancel(
        self,
        *,
        message_id: str,
        run_id: str,
        status: MessageStatus,
        error_code: str | None,
        completed_at: datetime,
    ) -> None:
        """Record a terminal, non-successful outcome.

        The message stays visible: a failure the user cannot see is a failure
        they cannot retry.
        """
        self._connection.execute(
            "UPDATE messages SET status = ?, error_code = ?, completed_at = ?"
            " WHERE message_id = ?",
            (status.value, error_code, to_utc_text(completed_at), message_id),
        )
        run_status = (
            RunStatus.CANCELLED
            if status is MessageStatus.CANCELLED
            else RunStatus.FAILED
        )
        self._connection.execute(
            "UPDATE message_runs SET status = ?, completed_at = ? WHERE run_id = ?",
            (run_status.value, to_utc_text(completed_at), run_id),
        )

    def set_run_snapshot(self, run_id: str, snapshot_id: str) -> None:
        """Record which snapshot actually answered.

        A queued run has not resolved one yet; writing it on completion is what
        binds the stored answer to the tree it examined, permanently.
        """
        self._connection.execute(
            "UPDATE message_runs SET snapshot_id = ? WHERE run_id = ?",
            (snapshot_id, run_id),
        )

    def set_run_warnings(self, run_id: str, warnings: Sequence[str]) -> None:
        """Record what the run warned about.

        A run is inserted while queued, before retrieval has warned about
        anything, so the column is written again on completion. Until
        P6-STREAM the submission response carried these straight from memory
        and nothing noticed they were never stored — an accepted turn returns
        before they exist, so a warning that is not persisted is a warning the
        user never sees.
        """
        encoded = json.dumps(list(warnings))
        if len(encoded.encode("utf-8")) > MAX_WARNINGS_BYTES:
            raise ValueError("run warnings exceed the stored bound")
        self._connection.execute(
            "UPDATE message_runs SET warnings_json = ? WHERE run_id = ?",
            (encoded, run_id),
        )

    def latest_run(self, message_id: str) -> RunRecord | None:
        """The most recent attempt, which is the one a reader is shown."""
        runs = self.list_runs(message_id)
        return runs[-1] if runs else None

    def create_retry_run(self, message_id: str, run: RunRecord) -> None:
        """Queue another attempt, preserving every prior one."""
        self._connection.execute(
            "UPDATE messages SET status = ?, error_code = NULL, completed_at = NULL"
            " WHERE message_id = ?",
            (MessageStatus.QUEUED.value, message_id),
        )
        self._insert_run(run)

    def list_messages(
        self,
        conversation_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[MessageRecord]:
        """Page a thread in sequence order."""
        clauses = ["conversation_id = ?"]
        parameters: list[Any] = [conversation_id]
        if cursor is not None:
            clauses.append("sequence_number > ?")
            parameters.append(int(cursor))

        where = " AND ".join(clauses)
        rows = self._connection.execute(
            "SELECT * FROM messages"
            f" WHERE {where}"
            " ORDER BY sequence_number LIMIT ?",
            (*parameters, limit + 1),
        ).fetchall()

        items = [_message_from_row(row) for row in rows[:limit]]
        next_cursor = (
            str(items[-1].sequence_number) if len(rows) > limit and items else None
        )
        return Page(items=tuple(items), next_cursor=next_cursor)

    def get_message(self, message_id: str) -> MessageRecord | None:
        row = self._connection.execute(
            "SELECT * FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return _message_from_row(row) if row is not None else None

    def list_runs(self, message_id: str) -> tuple[RunRecord, ...]:
        """Every attempt at this message, oldest first.

        `rowid` breaks ties, not `run_id`. Two attempts can share a timestamp —
        a retry of a run that failed immediately often does — and a run ID is a
        random hex string, so tie-breaking on it returns the attempts in an
        arbitrary order. That silently misrepresents the audit trail: it would
        show a retry as having happened before the attempt it retried. `rowid`
        is assigned in insertion order, which is the chronology being claimed.
        """
        rows = self._connection.execute(
            "SELECT * FROM message_runs WHERE message_id = ?"
            " ORDER BY created_at, rowid",
            (message_id,),
        ).fetchall()
        return tuple(_run_from_row(row) for row in rows)

    def get_evidence(self, message_id: str) -> tuple[MessageEvidenceRow, ...]:
        rows = self._connection.execute(
            "SELECT * FROM message_evidence WHERE message_id = ?"
            " ORDER BY citation_ordinal",
            (message_id,),
        ).fetchall()
        return tuple(
            MessageEvidenceRow(
                evidence_id=row["evidence_id"],
                citation_ordinal=row["citation_ordinal"],
                file_path=row["file_path"],
                symbol=row["symbol"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                content_hash=row["content_hash"],
                derivation=Derivation(row["derivation"]),
                confidence=row["confidence"],
                snapshot_id=row["snapshot_id"],
                claim_ids=tuple(json.loads(row["claim_ids_json"])),
            )
            for row in rows
        )

    def save_feedback(
        self,
        message_id: str,
        *,
        rating: str,
        reason_code: str | None,
        created_at: datetime,
        comment: str | None = None,
    ) -> None:
        """Store the user's current opinion, replacing any earlier one."""
        self._connection.execute(
            "INSERT INTO message_feedback"
            " (message_id, rating, reason_code, comment, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(message_id) DO UPDATE SET"
            " rating = excluded.rating, reason_code = excluded.reason_code,"
            " comment = excluded.comment, created_at = excluded.created_at",
            (message_id, rating, reason_code, comment, to_utc_text(created_at)),
        )

    # -- internals --------------------------------------------------------

    def _insert_message(self, record: MessageRecord) -> None:
        _check_content_bound(record.content)
        self._connection.execute(
            "INSERT INTO messages ("
            " message_id, conversation_id, role, status, sequence_number,"
            " content, error_code, created_at, completed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.message_id,
                record.conversation_id,
                record.role.value,
                record.status.value,
                record.sequence_number,
                record.content,
                record.error_code,
                to_utc_text(record.created_at),
                _optional_utc(record.completed_at),
            ),
        )

    def _insert_run(self, record: RunRecord) -> None:
        warnings = json.dumps(list(record.warnings))
        if len(warnings.encode("utf-8")) > MAX_WARNINGS_BYTES:
            raise ValueError("run warnings exceed the stored bound")
        self._connection.execute(
            "INSERT INTO message_runs ("
            " run_id, message_id, repository_id, snapshot_id, normalized_query,"
            " intent, retrieval_policy_version, status, latency_ms,"
            " warnings_json, created_at, completed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id,
                record.message_id,
                record.repository_id,
                record.snapshot_id,
                record.normalized_query,
                record.intent,
                record.retrieval_policy_version,
                record.status.value,
                record.latency_ms,
                warnings,
                to_utc_text(record.created_at),
                _optional_utc(record.completed_at),
            ),
        )

    def _touch_conversation(self, conversation_id: str, moment: datetime) -> None:
        self._connection.execute(
            "UPDATE conversations SET last_message_at = ?, updated_at = ?"
            " WHERE conversation_id = ?",
            (to_utc_text(moment), to_utc_text(moment), conversation_id),
        )

    def _touch_message_conversation(self, message_id: str, moment: datetime) -> None:
        self._connection.execute(
            "UPDATE conversations SET last_message_at = ?, updated_at = ?"
            " WHERE conversation_id = ("
            "  SELECT conversation_id FROM messages WHERE message_id = ?"
            " )",
            (to_utc_text(moment), to_utc_text(moment), message_id),
        )


def _check_content_bound(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_MESSAGE_CONTENT_BYTES:
        raise ValueError("message content exceeds the stored bound")


def _optional_utc(moment: datetime | None) -> str | None:
    return to_utc_text(moment) if moment is not None else None


def _conversation_from_row(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=row["conversation_id"],
        repository_id=row["repository_id"],
        title=row["title"],
        pinned_snapshot_policy=row["pinned_snapshot_policy"],
        created_at=from_utc_text(row["created_at"]),
        updated_at=from_utc_text(row["updated_at"]),
        last_message_at=_optional_from_text(row["last_message_at"]),
        archived_at=_optional_from_text(row["archived_at"]),
        deleted_at=_optional_from_text(row["deleted_at"]),
    )


def _message_from_row(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        role=MessageRole(row["role"]),
        status=MessageStatus(row["status"]),
        sequence_number=row["sequence_number"],
        content=row["content"],
        error_code=row["error_code"],
        created_at=from_utc_text(row["created_at"]),
        completed_at=_optional_from_text(row["completed_at"]),
    )


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        message_id=row["message_id"],
        repository_id=row["repository_id"],
        snapshot_id=row["snapshot_id"],
        normalized_query=row["normalized_query"],
        intent=row["intent"],
        retrieval_policy_version=row["retrieval_policy_version"],
        status=RunStatus(row["status"]),
        latency_ms=row["latency_ms"],
        warnings=tuple(json.loads(row["warnings_json"])),
        created_at=from_utc_text(row["created_at"]),
        completed_at=_optional_from_text(row["completed_at"]),
    )


def _optional_from_text(value: str | None) -> datetime | None:
    return from_utc_text(value) if value else None
