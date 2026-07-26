"""The FTS5 projection: completeness, scoping, and deletion."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.retrieval.fts_query import build_match_expression
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import (
    ChunkStore,
    FileStore,
    RepositoryStore,
    SearchStore,
    SnapshotStore,
)

CREATED_AT = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "db.sqlite") as open_connection:
        apply_migrations(open_connection)
        RepositoryStore(open_connection).add(
            Repository(
                repository_id="repo_1",
                display_name="demo",
                canonical_root="C:/repos/demo",
                created_at=CREATED_AT,
            )
        )
        snapshots = SnapshotStore(open_connection)
        files = FileStore(open_connection)
        for snapshot_id in ("snap_1", "snap_2"):
            snapshots.add_staging(_snapshot(snapshot_id))
            files.add_many(snapshot_id, [_file()])
        yield open_connection


def _snapshot(snapshot_id: str) -> Snapshot:
    return Snapshot(
        snapshot_id=snapshot_id,
        repository_id="repo_1",
        state=SnapshotState.INDEXING,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint=f"fingerprint-{snapshot_id}",
        file_count=1,
        parsed_file_count=1,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.0.0",
        index_version="1.0.0",
        created_at=CREATED_AT,
        activated_at=None,
    )


def _file() -> FileRecord:
    return FileRecord(
        file_id="file_1",
        relative_path="src/payments/service.py",
        display_path="src/payments/service.py",
        content_hash="hash",
        size_bytes=100,
        line_count=40,
        language="python",
        classification=FileClassification.SOURCE_CODE,
    )


def _chunk(
    logical_chunk_id: str = "chunk_1",
    *,
    text: str = "def capture: claim the idempotency key",
    qualified_name: str = "PaymentService.capture",
    part_index: int = 0,
    part_count: int = 1,
    start_line: int = 1,
    end_line: int = 4,
) -> LogicalChunk:
    return LogicalChunk(
        logical_chunk_id=logical_chunk_id,
        chunk_version_id=f"chunkv_{logical_chunk_id}_{part_index}",
        file_id="file_1",
        symbol_id="sym_1",
        role=ChunkRole.SYMBOL,
        qualified_name=qualified_name,
        heading_path="",
        start_line=start_line,
        end_line=end_line,
        content_hash="content",
        retrieval_text=text,
        part_index=part_index,
        part_count=part_count,
    )


def _index(
    connection: sqlite3.Connection, snapshot_id: str, *chunks: LogicalChunk
) -> SearchStore:
    ChunkStore(connection).add_many(snapshot_id, list(chunks))
    store = SearchStore(connection)
    store.index_chunks(
        snapshot_id, list(chunks), {"file_1": "src/payments/service.py"}
    )
    store.index_files(snapshot_id, [_file()])
    return store


def test_the_projection_covers_every_chunk_row(
    connection: sqlite3.Connection,
) -> None:
    store = _index(connection, "snap_1", _chunk("chunk_1"), _chunk("chunk_2"))

    chunk_rows, fts_rows = store.count_indexed("snap_1")
    assert chunk_rows == 2
    assert fts_rows == 2


def test_a_split_chunk_is_projected_once_per_part(
    connection: sqlite3.Connection,
) -> None:
    store = _index(
        connection,
        "snap_1",
        _chunk("chunk_big", part_index=0, part_count=2, text="first half"),
        _chunk(
            "chunk_big",
            part_index=1,
            part_count=2,
            text="second half",
            start_line=5,
            end_line=9,
        ),
    )

    chunk_rows, fts_rows = store.count_indexed("snap_1")
    assert (chunk_rows, fts_rows) == (2, 2)

    hits = store.search_chunks("snap_1", build_match_expression("second"), limit=10)
    assert len(hits) == 1
    assert (hits[0].start_line, hits[0].end_line) == (5, 9)


def test_content_search_returns_the_chunk_location(
    connection: sqlite3.Connection,
) -> None:
    store = _index(connection, "snap_1", _chunk("chunk_1"))

    hits = store.search_chunks(
        "snap_1", build_match_expression("idempotency"), limit=10
    )

    assert len(hits) == 1
    assert hits[0].relative_path == "src/payments/service.py"
    assert hits[0].qualified_name == "PaymentService.capture"
    assert hits[0].logical_chunk_id == "chunk_1"
    assert hits[0].symbol_id == "sym_1"


def test_symbol_names_are_searchable(connection: sqlite3.Connection) -> None:
    store = _index(connection, "snap_1", _chunk("chunk_1"))
    hits = store.search_chunks(
        "snap_1", build_match_expression("paymentservice.capture"), limit=10
    )
    assert len(hits) == 1


def test_file_paths_are_searchable(connection: sqlite3.Connection) -> None:
    store = _index(connection, "snap_1", _chunk("chunk_1"))
    hits = store.search_files("snap_1", build_match_expression("payments"), limit=10)
    assert [hit.relative_path for hit in hits] == ["src/payments/service.py"]


def test_the_projection_is_scoped_to_its_snapshot(
    connection: sqlite3.Connection,
) -> None:
    _index(connection, "snap_1", _chunk("chunk_1"))
    store = _index(connection, "snap_2", _chunk("chunk_2", text="unrelated content"))

    hits = store.search_chunks(
        "snap_1", build_match_expression("idempotency"), limit=10
    )
    assert [hit.logical_chunk_id for hit in hits] == ["chunk_1"]
    assert store.count_indexed("snap_2") == (1, 1)


def test_delete_for_snapshot_removes_only_that_snapshot(
    connection: sqlite3.Connection,
) -> None:
    _index(connection, "snap_1", _chunk("chunk_1"))
    store = _index(connection, "snap_2", _chunk("chunk_2"))

    store.delete_for_snapshot("snap_1")

    # The projection is dropped; the chunk rows it projected are not. Deleting
    # chunks is the snapshot's business, not the search index's.
    assert store.count_indexed("snap_1") == (1, 0)
    assert store.count_indexed("snap_2")[1] == 1
    assert store.search_files("snap_1", build_match_expression("payments"), 10) == ()
    assert store.search_chunks(
        "snap_1", build_match_expression("idempotency"), 10
    ) == ()


def test_ordering_is_deterministic_for_equal_ranks(
    connection: sqlite3.Connection,
) -> None:
    store = _index(
        connection,
        "snap_1",
        _chunk("chunk_b", text="idempotency", start_line=9, end_line=12),
        _chunk("chunk_a", text="idempotency", start_line=1, end_line=4),
    )

    first = [
        hit.logical_chunk_id
        for hit in store.search_chunks(
            "snap_1", build_match_expression("idempotency"), limit=10
        )
    ]
    second = [
        hit.logical_chunk_id
        for hit in store.search_chunks(
            "snap_1", build_match_expression("idempotency"), limit=10
        )
    ]
    assert first == second
    assert first == ["chunk_a", "chunk_b"]
