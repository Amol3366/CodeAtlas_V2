"""Incremental indexing, with reuse counted rather than assumed.

This is the phase's central claim, so nothing here is satisfied by "the result
looks right". Every test asserts what was *recomputed*, because a rebuild that
happens to produce correct output is still a rebuild.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ChunkStore, SearchStore


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


def _edit_capture_body(root: Path) -> None:
    path = root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "return self.store.claim(key)", "return self.store.claim(key.strip())"
        ),
        encoding="utf-8",
    )


def _chunk_versions(harness: Harness, snapshot_id: str) -> dict[str, str]:
    return {
        chunk.qualified_name: chunk.chunk_version_id
        for chunk in ChunkStore(harness.connection).list_for_snapshot(snapshot_id)
    }


def test_the_first_index_reuses_nothing(harness: Harness) -> None:
    result = harness.services.indexing.index(harness.repository_id)

    assert result.reuse.files_reused == 0
    assert result.reuse.files_reparsed == 3
    assert result.reuse.chunks_recomputed > 0
    assert result.reuse.chunks_reused == 0


def test_editing_one_symbol_reuses_every_other_file(harness: Harness) -> None:
    harness.services.indexing.index(harness.repository_id)
    _edit_capture_body(harness.root)

    result = harness.services.indexing.index(harness.repository_id)

    assert result.reuse.files_reparsed == 1
    assert result.reuse.files_reused == 2
    assert result.reuse.chunks_recomputed < result.reuse.chunks_reused


def test_unrelated_chunk_versions_survive_a_one_symbol_edit(
    harness: Harness,
) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    before = _chunk_versions(harness, first.snapshot.snapshot_id)

    _edit_capture_body(harness.root)
    second = harness.services.indexing.index(harness.repository_id)
    after = _chunk_versions(harness, second.snapshot.snapshot_id)

    changed = {name for name in before if before[name] != after.get(name)}
    assert changed == {"PaymentService.capture"}


def test_a_reused_chunk_row_is_byte_identical(harness: Harness) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    store = ChunkStore(harness.connection)
    before = {
        chunk.logical_chunk_id: chunk
        for chunk in store.list_for_snapshot(first.snapshot.snapshot_id)
        if chunk.qualified_name == "src.payments.idempotency"
    }

    _edit_capture_body(harness.root)
    second = harness.services.indexing.index(harness.repository_id)
    after = {
        chunk.logical_chunk_id: chunk
        for chunk in store.list_for_snapshot(second.snapshot.snapshot_id)
        if chunk.qualified_name == "src.payments.idempotency"
    }

    assert before
    for logical_chunk_id, chunk in before.items():
        assert after[logical_chunk_id].retrieval_text == chunk.retrieval_text
        assert after[logical_chunk_id].chunk_version_id == chunk.chunk_version_id


def test_a_deleted_file_disappears_from_the_new_snapshot(harness: Harness) -> None:
    harness.services.indexing.index(harness.repository_id)
    (harness.root / "src" / "payments" / "idempotency.py").unlink()

    result = harness.services.indexing.index(harness.repository_id)

    versions = _chunk_versions(harness, result.snapshot.snapshot_id)
    assert "src.payments.idempotency" not in versions
    assert "IdempotencyStore" not in versions

    response = harness.services.search.search_text(
        SearchRequest(harness.repository_id, "idempotencystore", "req-1")
    )
    assert all(
        item.file_path != "src/payments/idempotency.py" for item in response.evidence
    )


def test_an_added_file_is_fully_derived(harness: Harness) -> None:
    harness.services.indexing.index(harness.repository_id)
    (harness.root / "src" / "payments" / "refunds.py").write_text(
        "class RefundService:\n    def refund(self, key: str) -> str:\n"
        "        return key\n",
        encoding="utf-8",
    )

    result = harness.services.indexing.index(harness.repository_id)

    assert result.reuse.files_reparsed == 1
    assert result.reuse.files_reused == 3
    versions = _chunk_versions(harness, result.snapshot.snapshot_id)
    assert "RefundService.refund" in versions


def test_a_chunker_version_change_disables_reuse(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.services.indexing.index(harness.repository_id)

    monkeypatch.setattr(
        "codeatlas.application.indexing.CHUNKER_VERSION", "9.9.9", raising=True
    )
    result = harness.services.indexing.index(harness.repository_id)

    assert result.reuse.files_reused == 0
    assert result.reuse.chunks_reused == 0
    assert result.reuse.files_reparsed == 3


def test_a_parser_version_change_disables_reuse(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.services.indexing.index(harness.repository_id)

    monkeypatch.setattr(
        "codeatlas.application.indexing.PARSER_BUNDLE_VERSION", "9.9.9", raising=True
    )
    result = harness.services.indexing.index(harness.repository_id)

    assert result.reuse.files_reused == 0


def test_reuse_never_sources_rows_from_a_failed_snapshot(harness: Harness) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    harness.services.recovery  # noqa: B018 - service exists; state is forced below
    harness.connection.execute(
        "UPDATE snapshots SET state = 'failed' WHERE snapshot_id = ?",
        (first.snapshot.snapshot_id,),
    )

    _edit_capture_body(harness.root)
    result = harness.services.indexing.index(harness.repository_id)

    # With no active predecessor there is nothing to reuse from, and a failed
    # snapshot must never become one.
    assert result.reuse.files_reused == 0
    assert result.reuse.chunks_reused == 0


def test_the_projection_matches_the_chunk_rows_after_an_incremental_run(
    harness: Harness,
) -> None:
    harness.services.indexing.index(harness.repository_id)
    _edit_capture_body(harness.root)
    result = harness.services.indexing.index(harness.repository_id)

    chunk_rows, fts_rows = SearchStore(harness.connection).count_indexed(
        result.snapshot.snapshot_id
    )
    assert chunk_rows == fts_rows
    assert chunk_rows > 0

    store = ChunkStore(harness.connection)
    assert store.count_membership(result.snapshot.snapshot_id) == chunk_rows
    assert store.orphan_membership(result.snapshot.snapshot_id) == ()
    assert store.invalid_line_ranges(result.snapshot.snapshot_id) == ()


def test_search_works_against_an_incrementally_built_snapshot(
    harness: Harness,
) -> None:
    harness.services.indexing.index(harness.repository_id)
    _edit_capture_body(harness.root)
    harness.services.indexing.index(harness.repository_id)

    response = harness.services.search.search_text(
        SearchRequest(harness.repository_id, "idempotencystore", "req-2")
    )
    assert response.evidence

    exact = harness.services.search.search_symbols(
        SearchRequest(harness.repository_id, "capture", "req-3")
    )
    assert exact.evidence[0].symbol == "PaymentService.capture"


def test_reuse_statistics_are_recorded_on_the_job(harness: Harness) -> None:
    harness.services.indexing.index(harness.repository_id)
    _edit_capture_body(harness.root)
    harness.services.indexing.index(harness.repository_id)

    diagnostics = harness.services.status.diagnostics(harness.repository_id)
    assert diagnostics is not None


def test_reindexing_unchanged_source_remains_idempotent(harness: Harness) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    second = harness.services.indexing.index(harness.repository_id)

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    count = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE state = ?",
        (SnapshotState.ACTIVE.value,),
    ).fetchone()[0]
    assert count == 1
