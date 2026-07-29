"""Stale vectors, and why keeping them is safe.

This is gate condition 4. A vector store is append-friendly and a repository is
not: content is deleted, symbols are renamed, branches are switched. If
retrieval eligibility depended on the vector store forgetting things promptly,
every one of those events would be a race, and losing the race means citing
code that no longer exists.

So eligibility does not depend on it. SQLite snapshot membership decides, and
the vector store is allowed to hold whatever it likes — blueprint 8.20's
`old vector physically present != old vector eligible for retrieval`.

The tests below all take the same shape: put a vector in the store, take its
content out of the snapshot, and require that the search cannot return it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeatlas.semantic.membership import SnapshotMembershipFilter
from codeatlas.semantic.vector_store import (
    InMemoryVectorStore,
    VectorRecord,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_NAMESPACE = "fake_3d_l2-v1"


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-29T00:00:00Z')"
        )
        yield conn


def _snapshot(connection: sqlite3.Connection, snapshot_id: str, state: str) -> None:
    connection.execute(
        "INSERT INTO snapshots ("
        " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
        " working_tree_fingerprint, file_count, parsed_file_count,"
        " skipped_file_count, parse_error_count, parser_bundle_version,"
        " index_version, created_at, activated_at"
        ") VALUES (?, 'repo_1', ?, NULL, NULL, 0, 'fp', 1, 1, 0, 0, '1.0.0',"
        " '1.0.0', '2026-07-29T00:00:00Z', NULL)",
        (snapshot_id, state),
    )
    connection.execute(
        "INSERT INTO files ("
        " snapshot_id, file_id, relative_path, display_path, content_hash,"
        " size_bytes, line_count, language, classification"
        ") VALUES (?, 'file_1', 'a.py', 'a.py', 'fh', 1, 10, 'python',"
        " 'source_code')",
        (snapshot_id,),
    )


def _chunk(
    connection: sqlite3.Connection,
    snapshot_id: str,
    logical_chunk_id: str,
    content_hash: str,
) -> None:
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES (?, ?, ?, 'file_1', NULL, 'symbol', ?, '', 1, 5, ?, 'text', 0, 1)",
        (
            snapshot_id,
            logical_chunk_id,
            f"chunkv_{content_hash}",
            logical_chunk_id,
            content_hash,
        ),
    )
    connection.execute(
        "INSERT INTO snapshot_chunk_membership ("
        " snapshot_id, logical_chunk_id, chunk_version_id, part_index"
        ") VALUES (?, ?, ?, 0)",
        (snapshot_id, logical_chunk_id, f"chunkv_{content_hash}"),
    )


def _store_with(*hashes: str) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    store.upsert(
        _NAMESPACE,
        [
            VectorRecord(
                embedding_key=f"emb_{content_hash}",
                content_hash=content_hash,
                vector=[1.0, 0.0, 0.0],
            )
            for content_hash in hashes
        ],
    )
    return store


def test_a_vector_whose_content_is_in_the_snapshot_is_returned(
    connection: sqlite3.Connection,
) -> None:
    _snapshot(connection, "snap_1", "active")
    _chunk(connection, "snap_1", "chunk_a", "hash_a")
    store = _store_with("hash_a")

    matches = store.search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)
    eligible = SnapshotMembershipFilter(connection).keep_active("snap_1", matches)

    assert [candidate.logical_chunk_id for candidate in eligible] == ["chunk_a"]


def test_a_vector_whose_content_left_the_snapshot_cannot_be_returned(
    connection: sqlite3.Connection,
) -> None:
    """The deleted-code case. The vector is still physically present — that is
    the point — and it is still excluded."""
    _snapshot(connection, "snap_1", "active")
    _chunk(connection, "snap_1", "chunk_a", "hash_a")
    store = _store_with("hash_a", "hash_deleted")

    matches = store.search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)
    eligible = SnapshotMembershipFilter(connection).keep_active("snap_1", matches)

    assert store.count(_NAMESPACE) == 2, "the stale vector was not deleted"
    assert [candidate.content_hash for candidate in eligible] == ["hash_a"]


def test_another_snapshots_content_cannot_leak_in(
    connection: sqlite3.Connection,
) -> None:
    """Active-snapshot leakage is a release-blocking zero (Section 19.3). A
    superseded snapshot's chunks share the vector store with the active one, so
    the filter is the only thing separating them."""
    _snapshot(connection, "snap_old", "superseded")
    _chunk(connection, "snap_old", "chunk_old", "hash_old")
    _snapshot(connection, "snap_new", "active")
    _chunk(connection, "snap_new", "chunk_new", "hash_new")
    store = _store_with("hash_old", "hash_new")

    matches = store.search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)
    eligible = SnapshotMembershipFilter(connection).keep_active("snap_new", matches)

    assert [candidate.content_hash for candidate in eligible] == ["hash_new"]


def test_content_shared_by_two_snapshots_resolves_to_the_one_asked_for(
    connection: sqlite3.Connection,
) -> None:
    """Reuse is the normal case: an unchanged chunk keeps its content hash
    across snapshots and shares one vector. The filter must resolve that single
    vector to the chunk row of the snapshot being queried."""
    _snapshot(connection, "snap_old", "superseded")
    _chunk(connection, "snap_old", "chunk_a", "shared")
    _snapshot(connection, "snap_new", "active")
    _chunk(connection, "snap_new", "chunk_a", "shared")
    store = _store_with("shared")

    matches = store.search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)
    eligible = SnapshotMembershipFilter(connection).keep_active("snap_new", matches)

    assert len(eligible) == 1
    assert eligible[0].snapshot_id == "snap_new"


def test_the_filter_carries_the_lines_evidence_will_need(
    connection: sqlite3.Connection,
) -> None:
    """A semantic candidate has to become citable evidence, which means a file
    and a line range. Returning bare content hashes would push a second lookup
    onto every caller."""
    _snapshot(connection, "snap_1", "active")
    _chunk(connection, "snap_1", "chunk_a", "hash_a")

    matches = _store_with("hash_a").search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)
    [candidate] = SnapshotMembershipFilter(connection).keep_active("snap_1", matches)

    assert candidate.file_id == "file_1"
    assert candidate.start_line == 1
    assert candidate.end_line == 5
    assert candidate.score == pytest.approx(1.0)


def test_ranking_order_survives_the_filter(
    connection: sqlite3.Connection,
) -> None:
    """Filtering removes candidates; it must not reorder the survivors."""
    _snapshot(connection, "snap_1", "active")
    _chunk(connection, "snap_1", "chunk_a", "hash_a")
    _chunk(connection, "snap_1", "chunk_b", "hash_b")
    store = InMemoryVectorStore()
    store.upsert(
        _NAMESPACE,
        [
            VectorRecord("emb_a", "hash_a", [0.6, 0.8, 0.0]),
            VectorRecord("emb_b", "hash_b", [1.0, 0.0, 0.0]),
        ],
    )

    matches = store.search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)
    eligible = SnapshotMembershipFilter(connection).keep_active("snap_1", matches)

    assert [candidate.content_hash for candidate in eligible] == ["hash_b", "hash_a"]


def test_an_empty_search_result_is_not_a_query(
    connection: sqlite3.Connection,
) -> None:
    _snapshot(connection, "snap_1", "active")

    assert SnapshotMembershipFilter(connection).keep_active("snap_1", ()) == ()


def test_a_snapshot_with_no_chunks_yields_nothing(
    connection: sqlite3.Connection,
) -> None:
    """A repository indexed before chunking, or one mid-build. Neither may
    borrow another snapshot's vectors to look populated."""
    _snapshot(connection, "snap_1", "active")
    matches = _store_with("hash_a").search(_NAMESPACE, [1.0, 0.0, 0.0], limit=10)

    assert SnapshotMembershipFilter(connection).keep_active("snap_1", matches) == ()
