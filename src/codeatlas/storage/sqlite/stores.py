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
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.domain.symbols import SymbolRecord, Visibility
from codeatlas.storage.sqlite.connection import from_utc_text, to_utc_text

_ACTIVE_JOB_STATUSES = ("queued", "running")


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
            " index_version, created_at, activated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
