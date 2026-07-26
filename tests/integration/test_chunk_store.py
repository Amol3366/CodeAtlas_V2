"""Chunk persistence, snapshot scoping, and reuse copying against real SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import (
    ChunkStore,
    FileStore,
    RepositoryStore,
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
            files.add_many(snapshot_id, [_file("file_1"), _file("file_2", "src/b.py")])
        yield open_connection


def _snapshot(snapshot_id: str) -> Snapshot:
    return Snapshot(
        snapshot_id=snapshot_id,
        repository_id="repo_1",
        state=SnapshotState.CHUNKING,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint=f"fingerprint-{snapshot_id}",
        file_count=2,
        parsed_file_count=2,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.0.0",
        index_version="1.0.0",
        created_at=CREATED_AT,
        activated_at=None,
    )


def _file(file_id: str, relative_path: str = "src/a.py") -> FileRecord:
    return FileRecord(
        file_id=file_id,
        relative_path=relative_path,
        display_path=relative_path,
        content_hash="hash",
        size_bytes=100,
        line_count=40,
        language="python",
        classification=FileClassification.SOURCE_CODE,
    )


def _chunk(
    logical_chunk_id: str = "chunk_1",
    file_id: str = "file_1",
    *,
    role: ChunkRole = ChunkRole.SYMBOL,
    qualified_name: str = "A.run",
    start_line: int = 1,
    end_line: int = 4,
    part_index: int = 0,
    part_count: int = 1,
    version: str = "chunkv_1",
) -> LogicalChunk:
    return LogicalChunk(
        logical_chunk_id=logical_chunk_id,
        chunk_version_id=version,
        file_id=file_id,
        symbol_id="sym_1",
        role=role,
        qualified_name=qualified_name,
        heading_path="",
        start_line=start_line,
        end_line=end_line,
        content_hash="content-hash",
        retrieval_text="PATH: src/a.py\nCODE:\n...",
        part_index=part_index,
        part_count=part_count,
    )


def test_chunks_round_trip_with_every_field(connection: sqlite3.Connection) -> None:
    store = ChunkStore(connection)
    original = _chunk(role=ChunkRole.DOCUMENT_SECTION)
    store.add_many("snap_1", [original])

    stored = store.list_for_snapshot("snap_1")
    assert stored == (original,)


def test_chunks_are_scoped_to_their_snapshot(connection: sqlite3.Connection) -> None:
    store = ChunkStore(connection)
    store.add_many("snap_1", [_chunk("chunk_1")])
    store.add_many("snap_2", [_chunk("chunk_2")])

    assert [item.logical_chunk_id for item in store.list_for_snapshot("snap_1")] == [
        "chunk_1"
    ]
    assert store.count_for_snapshot("snap_1") == 1
    assert store.count_for_snapshot("snap_2") == 1


def test_list_for_file_returns_only_that_file(connection: sqlite3.Connection) -> None:
    store = ChunkStore(connection)
    store.add_many(
        "snap_1",
        [_chunk("chunk_1", "file_1"), _chunk("chunk_2", "file_2")],
    )

    listed = store.list_for_file("snap_1", "file_2")
    assert [item.logical_chunk_id for item in listed] == ["chunk_2"]


def test_listing_is_ordered_deterministically(connection: sqlite3.Connection) -> None:
    store = ChunkStore(connection)
    store.add_many(
        "snap_1",
        [
            _chunk("chunk_b", "file_2", start_line=9, end_line=12),
            _chunk("chunk_a", "file_1", start_line=5, end_line=8),
            _chunk("chunk_a2", "file_1", start_line=1, end_line=4),
        ],
    )

    listed = [item.logical_chunk_id for item in store.list_for_snapshot("snap_1")]
    assert listed == ["chunk_a2", "chunk_a", "chunk_b"]


def test_a_split_symbol_stores_one_row_per_part(
    connection: sqlite3.Connection,
) -> None:
    store = ChunkStore(connection)
    store.add_many(
        "snap_1",
        [
            _chunk(
                "chunk_big",
                role=ChunkRole.SYMBOL_PART,
                start_line=1,
                end_line=10,
                part_index=0,
                part_count=2,
                version="chunkv_part0",
            ),
            _chunk(
                "chunk_big",
                role=ChunkRole.SYMBOL_PART,
                start_line=11,
                end_line=20,
                part_index=1,
                part_count=2,
                version="chunkv_part1",
            ),
        ],
    )

    stored = store.list_for_snapshot("snap_1")
    assert [item.part_index for item in stored] == [0, 1]
    assert store.count_for_snapshot("snap_1") == 2
    membership = connection.execute(
        "SELECT COUNT(*) FROM snapshot_chunk_membership WHERE snapshot_id = 'snap_1'"
    ).fetchone()[0]
    assert membership == 2


def test_membership_is_written_for_every_chunk(
    connection: sqlite3.Connection,
) -> None:
    store = ChunkStore(connection)
    store.add_many("snap_1", [_chunk("chunk_1"), _chunk("chunk_2", "file_2")])

    rows = connection.execute(
        "SELECT logical_chunk_id, chunk_version_id FROM snapshot_chunk_membership"
        " WHERE snapshot_id = 'snap_1' ORDER BY logical_chunk_id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("chunk_1", "chunkv_1"),
        ("chunk_2", "chunkv_1"),
    ]


def test_copy_from_snapshot_reports_how_many_rows_were_reused(
    connection: sqlite3.Connection,
) -> None:
    store = ChunkStore(connection)
    store.add_many(
        "snap_1",
        [_chunk("chunk_1", "file_1"), _chunk("chunk_2", "file_2")],
    )

    copied = store.copy_from_snapshot("snap_1", "snap_2", ["file_1"])

    assert copied == 1
    reused = store.list_for_snapshot("snap_2")
    assert [item.logical_chunk_id for item in reused] == ["chunk_1"]
    assert reused[0].chunk_version_id == "chunkv_1"


def test_copy_from_snapshot_copies_membership_too(
    connection: sqlite3.Connection,
) -> None:
    store = ChunkStore(connection)
    store.add_many("snap_1", [_chunk("chunk_1", "file_1")])

    store.copy_from_snapshot("snap_1", "snap_2", ["file_1"])

    membership = connection.execute(
        "SELECT chunk_version_id FROM snapshot_chunk_membership"
        " WHERE snapshot_id = 'snap_2'"
    ).fetchall()
    assert [row[0] for row in membership] == ["chunkv_1"]


def test_copying_no_files_copies_nothing(connection: sqlite3.Connection) -> None:
    store = ChunkStore(connection)
    store.add_many("snap_1", [_chunk("chunk_1", "file_1")])
    assert store.copy_from_snapshot("snap_1", "snap_2", []) == 0
    assert store.count_for_snapshot("snap_2") == 0


def test_invalid_line_ranges_reports_a_chunk_beyond_its_file(
    connection: sqlite3.Connection,
) -> None:
    store = ChunkStore(connection)
    store.add_many(
        "snap_1",
        [
            _chunk("chunk_ok", start_line=1, end_line=40),
            _chunk("chunk_past_end", start_line=1, end_line=41),
            _chunk("chunk_inverted", start_line=9, end_line=8),
            _chunk("chunk_zero", start_line=0, end_line=3),
        ],
    )

    invalid = set(store.invalid_line_ranges("snap_1"))

    assert invalid == {"chunk_past_end", "chunk_inverted", "chunk_zero"}


def test_a_chunk_cannot_reference_a_file_outside_its_snapshot(
    connection: sqlite3.Connection,
) -> None:
    store = ChunkStore(connection)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_many("snap_1", [_chunk("chunk_1", "file_missing")])
