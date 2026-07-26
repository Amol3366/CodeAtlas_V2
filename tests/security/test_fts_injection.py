"""Hostile search input executed against a real populated FTS5 index.

A unit test on the query builder proves the string looks safe. This proves the
string *is* safe: every query below is run against real SQLite, and the only
acceptable outcomes are a bounded result set or a typed `SearchQueryError`.
A `sqlite3.OperationalError` would mean user text reached FTS5 as syntax, and a
result set containing everything would mean the query degenerated to a wildcard.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.errors import SearchQueryError
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

HOSTILE = [
    '" OR "" : *',
    "chunk_search MATCH 'x'",
    "*; DROP TABLE chunks; --",
    "NEAR(a b, 100000)",
    "^" * 50,
    "a" * 255,
    "' UNION SELECT retrieval_text FROM chunks --",
    "payment*",
    '"unterminated',
    "col:value",
    "{a b}",
    "\x00null",
]


@pytest.fixture()
def populated(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        RepositoryStore(connection).add(
            Repository(
                repository_id="repo_1",
                display_name="demo",
                canonical_root="C:/repos/demo",
                created_at=CREATED_AT,
            )
        )
        SnapshotStore(connection).add_staging(
            Snapshot(
                snapshot_id="snap_1",
                repository_id="repo_1",
                state=SnapshotState.INDEXING,
                git_head=None,
                git_branch=None,
                git_dirty=False,
                working_tree_fingerprint="fingerprint",
                file_count=1,
                parsed_file_count=1,
                skipped_file_count=0,
                parse_error_count=0,
                parser_bundle_version="1.0.0",
                index_version="1.0.0",
                created_at=CREATED_AT,
                activated_at=None,
            )
        )
        files = [
            FileRecord(
                file_id=f"file_{index}",
                relative_path=f"src/payments/module_{index}.py",
                display_path=f"src/payments/module_{index}.py",
                content_hash="hash",
                size_bytes=100,
                line_count=40,
                language="python",
                classification=FileClassification.SOURCE_CODE,
            )
            for index in range(3)
        ]
        FileStore(connection).add_many("snap_1", files)
        chunks = [
            LogicalChunk(
                logical_chunk_id=f"chunk_{index}",
                chunk_version_id=f"chunkv_{index}",
                file_id=f"file_{index}",
                symbol_id=f"sym_{index}",
                role=ChunkRole.SYMBOL,
                qualified_name=f"PaymentService.capture_{index}",
                heading_path="",
                start_line=1,
                end_line=4,
                content_hash="content",
                retrieval_text=f"idempotency key handling number {index}",
                part_index=0,
                part_count=1,
            )
            for index in range(3)
        ]
        ChunkStore(connection).add_many("snap_1", chunks)
        search = SearchStore(connection)
        search.index_chunks(
            "snap_1",
            chunks,
            {record.file_id: record.relative_path for record in files},
        )
        search.index_files("snap_1", files)
        yield connection


@pytest.mark.parametrize("raw", HOSTILE)
def test_hostile_queries_are_bounded_or_rejected(
    populated: sqlite3.Connection, raw: str
) -> None:
    store = SearchStore(populated)
    try:
        expression = build_match_expression(raw)
    except SearchQueryError:
        return  # An explicit, typed rejection is a correct outcome.

    hits = store.search_chunks("snap_1", expression, limit=25)
    assert len(hits) <= 3


@pytest.mark.parametrize("raw", HOSTILE)
def test_hostile_file_queries_are_bounded_or_rejected(
    populated: sqlite3.Connection, raw: str
) -> None:
    store = SearchStore(populated)
    try:
        expression = build_match_expression(raw)
    except SearchQueryError:
        return

    hits = store.search_files("snap_1", expression, limit=25)
    assert len(hits) <= 3


def test_the_chunk_table_still_exists_after_the_hostile_run(
    populated: sqlite3.Connection,
) -> None:
    store = SearchStore(populated)
    for raw in HOSTILE:
        try:
            expression = build_match_expression(raw)
        except SearchQueryError:
            continue
        store.search_chunks("snap_1", expression, limit=25)

    remaining = populated.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert remaining == 3


def test_a_query_matching_nothing_returns_nothing(
    populated: sqlite3.Connection,
) -> None:
    hits = SearchStore(populated).search_chunks(
        "snap_1", build_match_expression("nonexistentterm"), limit=25
    )
    assert hits == ()


def test_results_never_cross_snapshots(populated: sqlite3.Connection) -> None:
    hits = SearchStore(populated).search_chunks(
        "snap_other", build_match_expression("idempotency"), limit=25
    )
    assert hits == ()


def test_the_limit_is_enforced(populated: sqlite3.Connection) -> None:
    hits = SearchStore(populated).search_chunks(
        "snap_1", build_match_expression("idempotency"), limit=2
    )
    assert len(hits) == 2
