"""Snapshot isolation: staging invisibility and stale-entity exclusion.

A snapshot under construction must be unreachable, and a snapshot that has been
superseded must stay unreachable even though its rows physically remain. These
are the two ways an index quietly starts lying, so both are asserted directly
against the database as well as through the services.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.indexing import SnapshotValidationError
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ChunkStore, SnapshotStore


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    root: Path


@pytest.fixture()
def harness(tmp_path: Path, sample_repo: Path) -> Iterator[Harness]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=sample_repo,
        )


def _add_symbol(root: Path, name: str) -> None:
    path = root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + f"\n    def {name}(self, key: str) -> str:\n        return key\n",
        encoding="utf-8",
    )


# Scenario 1 — staging invisibility.


def test_a_staged_snapshot_is_invisible_to_every_query(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    _add_symbol(harness.root, "staged_only")

    def refuse(self: SnapshotStore, snapshot_id: str, activated_at: object) -> None:
        raise RuntimeError("process died before activation")

    monkeypatch.setattr(SnapshotStore, "activate", refuse)
    with pytest.raises(RuntimeError):
        harness.services.indexing.index(harness.repository_id)

    active = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert active is not None
    assert active.snapshot_id == first.snapshot.snapshot_id

    lookup = harness.services.lookup.lookup(
        SymbolLookupRequest(harness.repository_id, "staged_only", "req-1")
    )
    assert lookup.evidence == []

    search = harness.services.search.search_text(
        SearchRequest(harness.repository_id, "staged_only", "req-2")
    )
    assert search.evidence == []
    assert search.snapshot.snapshot_id == first.snapshot.snapshot_id


def test_a_staged_snapshot_never_holds_the_active_state(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.services.indexing.index(harness.repository_id)
    _add_symbol(harness.root, "never_active")

    def refuse(self: SnapshotStore, snapshot_id: str, activated_at: object) -> None:
        raise RuntimeError("process died before activation")

    monkeypatch.setattr(SnapshotStore, "activate", refuse)
    with pytest.raises(RuntimeError):
        harness.services.indexing.index(harness.repository_id)

    count = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE state = ?",
        (SnapshotState.ACTIVE.value,),
    ).fetchone()[0]
    assert count == 1


# Scenario 3 — an incomplete FTS projection must not activate.


def test_a_partial_projection_is_caught_by_validation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    _add_symbol(harness.root, "partial_projection")

    from codeatlas.storage.sqlite.stores import SearchStore

    original = SearchStore.index_chunks

    def truncated(
        self: SearchStore,
        snapshot_id: str,
        chunks: object,
        paths_by_file_id: object,
    ) -> None:
        # Simulate a write that died part-way through the projection.
        assert isinstance(chunks, list | tuple)
        original(self, snapshot_id, list(chunks)[:1], paths_by_file_id)  # type: ignore[arg-type]

    monkeypatch.setattr(SearchStore, "index_chunks", truncated)
    with pytest.raises(SnapshotValidationError):
        harness.services.indexing.index(harness.repository_id)

    active = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert active is not None
    assert active.snapshot_id == first.snapshot.snapshot_id


# Scenario 4 — stale entities cannot appear in active results.


def test_a_deleted_symbol_cannot_be_returned_after_reindexing(
    harness: Harness,
) -> None:
    _add_symbol(harness.root, "temporary_helper")
    first = harness.services.indexing.index(harness.repository_id)

    found = harness.services.lookup.lookup(
        SymbolLookupRequest(harness.repository_id, "temporary_helper", "req-3")
    )
    assert found.evidence

    path = harness.root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "\n    def temporary_helper(self, key: str) -> str:\n        return key\n",
            "\n",
        ),
        encoding="utf-8",
    )
    second = harness.services.indexing.index(harness.repository_id)

    gone = harness.services.lookup.lookup(
        SymbolLookupRequest(harness.repository_id, "temporary_helper", "req-4")
    )
    assert gone.evidence == []
    assert "NO_EXACT_SYMBOL_MATCH" in gone.warnings

    searched = harness.services.search.search_text(
        SearchRequest(harness.repository_id, "temporary_helper", "req-5")
    )
    assert searched.evidence == []

    # The rows still exist physically in the superseded snapshot; membership,
    # not deletion, is what makes them unreachable.
    physical = harness.connection.execute(
        "SELECT COUNT(*) FROM symbols WHERE snapshot_id = ? AND name = ?",
        (first.snapshot.snapshot_id, "temporary_helper"),
    ).fetchone()[0]
    assert physical == 1
    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id


def test_chunks_from_a_superseded_snapshot_are_never_searched(
    harness: Harness,
) -> None:
    _add_symbol(harness.root, "superseded_marker")
    first = harness.services.indexing.index(harness.repository_id)

    path = harness.root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace("superseded_marker", "renamed_marker"),
        encoding="utf-8",
    )
    harness.services.indexing.index(harness.repository_id)

    response = harness.services.search.search_text(
        SearchRequest(harness.repository_id, "superseded_marker", "req-6")
    )
    assert response.evidence == []

    stale_rows = ChunkStore(harness.connection).list_for_snapshot(
        first.snapshot.snapshot_id
    )
    assert any("superseded_marker" in chunk.retrieval_text for chunk in stale_rows)


# Scenario 5 — rollback restores the previous snapshot, results included.


def test_rollback_reverts_search_results(harness: Harness) -> None:
    _add_symbol(harness.root, "original_only")
    first = harness.services.indexing.index(harness.repository_id)

    path = harness.root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace("original_only", "replacement_only"),
        encoding="utf-8",
    )
    harness.services.indexing.index(harness.repository_id)
    assert harness.services.search.search_text(
        SearchRequest(harness.repository_id, "replacement_only", "req-7")
    ).evidence

    # The new snapshot's evidence would be read from a file that has since been
    # restored, so the file is restored with it.
    path.write_text(
        path.read_text(encoding="utf-8").replace("replacement_only", "original_only"),
        encoding="utf-8",
    )
    restored = harness.services.recovery.rollback(harness.repository_id)

    assert restored.snapshot_id == first.snapshot.snapshot_id
    assert harness.services.search.search_text(
        SearchRequest(harness.repository_id, "original_only", "req-8")
    ).evidence
    assert (
        harness.services.search.search_text(
            SearchRequest(harness.repository_id, "replacement_only", "req-9")
        ).evidence
        == []
    )


# Scenario 6 — sequential runs never leave two active snapshots.


def test_repeated_indexing_never_leaves_two_active_snapshots(
    harness: Harness,
) -> None:
    for index in range(4):
        harness.services.indexing.index(harness.repository_id)
        _add_symbol(harness.root, f"iteration_{index}")
    harness.services.indexing.index(harness.repository_id)

    count = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE state = ?",
        (SnapshotState.ACTIVE.value,),
    ).fetchone()[0]
    assert count == 1


def test_every_active_chunk_belongs_to_the_active_snapshot(
    harness: Harness,
) -> None:
    harness.services.indexing.index(harness.repository_id)
    _add_symbol(harness.root, "second_pass")
    harness.services.indexing.index(harness.repository_id)

    active = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert active is not None

    response = harness.services.search.search_text(
        SearchRequest(harness.repository_id, "capture", "req-10")
    )
    assert all(
        item.snapshot_id == active.snapshot_id for item in response.evidence
    )
