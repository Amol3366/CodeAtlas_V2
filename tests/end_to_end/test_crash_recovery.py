"""Crash recovery across process restarts, and bounded behavior on large files.

Every test here kills a run at a point where an index could plausibly be left
inconsistent, then reopens the database as a new process would and asserts the
previous active snapshot still answers correctly.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.chunking.chunker import HARD_MAX_CHARACTERS
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ChunkStore, SnapshotStore


def _register_and_index(database: Path, root: Path) -> str:
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        return repository.repository_id


def _add_symbol(root: Path, name: str) -> None:
    path = root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + f"\n    def {name}(self, key: str) -> str:\n        return key\n",
        encoding="utf-8",
    )


def test_a_crash_between_staging_and_activation_leaves_the_index_usable(
    tmp_path: Path, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _register_and_index(database, sample_repo)
    _add_symbol(sample_repo, "crashed_run")

    # The "process" dies after staging, before activation.
    with connect(database) as connection:
        services = build_services(connection)
        before = services.indexing.get_active_snapshot(repository_id)
        assert before is not None

        def die(self: SnapshotStore, snapshot_id: str, activated_at: object) -> None:
            raise RuntimeError("process died before activation")

        monkeypatch.setattr(SnapshotStore, "activate", die)
        with pytest.raises(RuntimeError):
            services.indexing.index(repository_id)

    monkeypatch.undo()

    # A new process starts: recovery runs during service construction.
    with connect(database) as connection:
        services = build_services(connection)
        after = services.indexing.get_active_snapshot(repository_id)
        assert after is not None
        assert after.snapshot_id == before.snapshot_id

        stranded = connection.execute(
            "SELECT COUNT(*) FROM snapshots WHERE state IN"
            " ('discovered','scanning','parsing','chunking','indexing','validating')"
        ).fetchone()[0]
        assert stranded == 0

        # A file untouched by the crashed run still answers with evidence.
        response = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "IdempotencyStore.claim", "req-1")
        )
        assert response.evidence
        assert response.snapshot.snapshot_id == before.snapshot_id

        # The edited file drifted from the snapshot, so its evidence is
        # withheld rather than shown — the crash did not change that rule.
        drifted = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "PaymentService.capture", "req-1b")
        )
        assert drifted.evidence == []
        assert "EVIDENCE_STALE_FILE_CONTENT" in drifted.warnings


def test_the_repository_can_be_reindexed_after_a_crash(
    tmp_path: Path, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _register_and_index(database, sample_repo)
    _add_symbol(sample_repo, "recovered_later")

    with connect(database) as connection:
        services = build_services(connection)

        def die(self: SnapshotStore, snapshot_id: str, activated_at: object) -> None:
            raise RuntimeError("process died before activation")

        monkeypatch.setattr(SnapshotStore, "activate", die)
        with pytest.raises(RuntimeError):
            services.indexing.index(repository_id)

    monkeypatch.undo()

    with connect(database) as connection:
        services = build_services(connection)
        result = services.indexing.index(repository_id)
        assert result.snapshot.state is SnapshotState.ACTIVE

        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "recovered_later", "req-2")
        )
        assert found.evidence


def test_chat_and_search_survive_a_backend_restart(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _register_and_index(database, sample_repo)

    with connect(database) as connection:
        services = build_services(connection)
        first = services.search.search_text(
            SearchRequest(repository_id, "idempotencystore", "req-3")
        )

    with connect(database) as connection:
        services = build_services(connection)
        second = services.search.search_text(
            SearchRequest(repository_id, "idempotencystore", "req-4")
        )

    assert first.evidence
    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence
    ]


def test_a_large_file_chunks_within_bounds_and_without_quadratic_time(
    tmp_path: Path, sample_repo: Path
) -> None:
    # Close to, but under, the 2 MB scan limit.
    body = "\n".join(
        f"    value_{index} = {index}  # padding to grow the file"
        for index in range(30_000)
    )
    (sample_repo / "src" / "payments" / "large.py").write_text(
        f"def large() -> None:\n{body}\n", encoding="utf-8"
    )

    database = tmp_path / "db.sqlite"
    started = time.perf_counter()
    repository_id = _register_and_index(database, sample_repo)
    elapsed = time.perf_counter() - started

    # Generous on purpose: this catches quadratic behavior, not slow hardware.
    assert elapsed < 60.0

    with connect(database) as connection:
        services = build_services(connection)
        snapshot = services.indexing.get_active_snapshot(repository_id)
        assert snapshot is not None
        chunks = ChunkStore(connection).list_for_snapshot(snapshot.snapshot_id)

        assert chunks
        assert all(
            len(chunk.retrieval_text) <= HARD_MAX_CHARACTERS for chunk in chunks
        )
        parts = [chunk for chunk in chunks if chunk.part_count > 1]
        assert parts
        assert {chunk.part_index for chunk in parts} == set(
            range(max(chunk.part_index for chunk in parts) + 1)
        )

        response = services.search.search_text(
            SearchRequest(repository_id, "padding", "req-5")
        )
        assert response.evidence
