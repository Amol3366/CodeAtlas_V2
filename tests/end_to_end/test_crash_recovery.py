"""Crash recovery across process restarts, and bounded behavior on large files.

Every test here kills a run at a point where an index could plausibly be left
inconsistent, then reopens the database as a new process would and asserts the
previous active snapshot still answers correctly.
"""

from __future__ import annotations

import subprocess
import sys
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


_CHILD_PROGRAM = """
import sys
from pathlib import Path
from codeatlas.application.container import build_services
from codeatlas.storage.sqlite.connection import connect

database, repository_id = Path(sys.argv[1]), sys.argv[2]
with connect(database) as connection:
    services = build_services(connection)
    services.indexing.index(repository_id)
"""


def test_a_genuinely_killed_process_is_recovered_and_can_reindex(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The state every fast crash test assumes, produced by a real kill.

    The other tests in this area write the post-kill state directly, which is
    fast and deterministic but asserts a state we *believe* a kill produces.
    This one kills a real process — no `except`, no `finally`, no atexit — and
    proves the belief. It is the slow test that keeps the quick ones honest.
    """
    database = tmp_path / "db.sqlite"

    # Enough files that indexing outlives the poll below. A repository that
    # indexes in 50 ms would be finished before any kill could land mid-run,
    # and the test would silently prove nothing.
    package = sample_repo / "src" / "bulk"
    package.mkdir(parents=True, exist_ok=True)
    for index in range(400):
        (package / f"module_{index}.py").write_text(
            f"class Bulk{index}:\n"
            f"    def method(self) -> int:\n"
            f"        return {index}\n",
            encoding="utf-8",
        )

    repository_id = _register_and_index(database, sample_repo)
    (package / "module_0.py").write_text(
        "class Bulk0:\n    def method(self) -> int:\n        return 999\n",
        encoding="utf-8",
    )

    # Fixed argv, no shell: nothing here is interpolated from user input.
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD_PROGRAM, str(database), repository_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Kill as soon as the job row exists. `index()` writes it before it
        # scans, so its presence means the run is genuinely under way.
        deadline = time.monotonic() + 60.0
        job_id: str | None = None
        # One connection for the whole poll. Reopening every 10 ms while the
        # child writes hits "disk I/O error" on Windows, which is contention
        # for the WAL side files rather than anything wrong with the code
        # under test.
        with connect(database) as watcher:
            while time.monotonic() < deadline and job_id is None:
                if child.poll() is not None:
                    # Report why it exited. A silent "it finished too fast"
                    # hides a child that in fact crashed on startup, and the
                    # test would then be measuring nothing.
                    _, stderr = child.communicate()
                    pytest.fail(
                        "the child exited before it could be killed"
                        f" (code {child.returncode}):"
                        f" {stderr.decode(errors='replace')}"
                    )
                row = watcher.execute(
                    "SELECT job_id FROM index_jobs WHERE status = 'running'"
                    " ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                job_id = None if row is None else str(row[0])
                if job_id is None:
                    time.sleep(0.01)
        assert job_id is not None, "no indexing run started"
        child.kill()
    finally:
        child.wait(timeout=30)

    # A killed process runs no cleanup, so the job it opened is still running.
    with connect(database) as connection:
        status = connection.execute(
            "SELECT status FROM index_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
    assert status == "running", "a killed process should leave its job open"

    # A new process starts. Recovery must heal the job, say what it found, and
    # leave the repository indexable again.
    with connect(database) as connection:
        services = build_services(connection)
        diagnostics = services.status.diagnostics(repository_id)
        assert diagnostics.interrupted_run is not None
        assert "INDEX_RUN_INTERRUPTED" in diagnostics.warnings

        result = services.indexing.index(repository_id)
        assert result.snapshot.state is SnapshotState.ACTIVE

        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "Bulk0.method", "req-kill")
        )
        assert found.evidence


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
