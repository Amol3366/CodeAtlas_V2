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

from codeatlas.contracts import SymbolKind
from codeatlas.domain.chunks import ChunkRole, LogicalChunk
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
            " index_version, created_at, activated_at, chunker_version"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
