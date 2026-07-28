"""Indexing keeps its own history bounded.

`SnapshotRecoveryService.prune` has existed since Phase 2 and documented the
policy — keep the active snapshot and the newest superseded one — but **nothing
called it**. Every index left its predecessor behind forever, with all of that
snapshot's files, symbols, relations, chunks, and FTS rows.

Before Phase 6 that was slow-burning: you reindexed when you chose to. The
watcher changed the arithmetic. A repository being edited all day is reindexed
all day, and each one added another permanent copy — found by the P6-08
performance measurement, where the packaged server stopped answering *any*
request after enough of them had piled up.

Retention is applied where the snapshots are made, so the bound holds for every
caller: the CLI, the API, the watcher, and the reconciling scan alike.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@dataclass(frozen=True)
class Registered:
    """A registered repository and the connection that can be counted."""

    connection: Connection
    services: ApplicationServices
    repository_id: str

    def snapshot_count(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM snapshots WHERE repository_id = ?",
                (self.repository_id,),
            ).fetchone()[0]
        )


@pytest.fixture()
def indexed(tmp_path: Path, sample_repo: Path) -> Iterator[Registered]:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        yield Registered(connection, services, repository.repository_id)


def _edit(repository_root: Path, marker: str) -> None:
    target = repository_root / "src" / "payments" / "service.py"
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n# {marker}\n", encoding="utf-8"
    )


def test_repeated_indexing_does_not_accumulate_snapshots(
    indexed: Registered, sample_repo: Path
) -> None:
    """The defect, stated as a bound: ten reindexes, not ten snapshots."""
    services = indexed.services
    repository_id = indexed.repository_id

    for run in range(10):
        _edit(sample_repo, f"edit-{run}")
        services.indexing.index(repository_id)

    assert indexed.snapshot_count() <= 2


def test_the_retained_snapshot_is_still_a_rollback_target(
    indexed: Registered, sample_repo: Path
) -> None:
    """Retention keeps one superseded snapshot precisely so rollback survives.

    A bound of "active only" would be smaller and would silently remove the
    recovery path Phase 2 built.
    """
    services = indexed.services
    repository_id = indexed.repository_id

    for run in range(5):
        _edit(sample_repo, f"edit-{run}")
        services.indexing.index(repository_id)

    active_before = services.indexing.get_active_snapshot(repository_id)
    restored = services.recovery.rollback(repository_id)

    assert active_before is not None
    assert restored.snapshot_id != active_before.snapshot_id
    assert restored.state is SnapshotState.ACTIVE


def test_pruned_snapshots_leave_no_searchable_orphans(
    indexed: Registered, sample_repo: Path
) -> None:
    """FTS5 virtual tables have no foreign keys, so a cascade cannot reach them.
    A pruned snapshot that kept its projections would still be searchable."""
    services = indexed.services
    repository_id = indexed.repository_id

    for run in range(6):
        _edit(sample_repo, f"edit-{run}")
        services.indexing.index(repository_id)

    live = {
        str(row[0])
        for row in indexed.connection.execute(
            "SELECT snapshot_id FROM snapshots WHERE repository_id = ?",
            (repository_id,),
        ).fetchall()
    }
    projected = {
        str(row[0])
        for row in indexed.connection.execute(
            "SELECT DISTINCT snapshot_id FROM file_search"
        ).fetchall()
    }

    assert projected <= live, "a pruned snapshot is still searchable"


def test_the_active_snapshot_still_answers_after_pruning(
    indexed: Registered, sample_repo: Path
) -> None:
    """Retention must not be able to take the snapshot being queried."""
    services = indexed.services
    repository_id = indexed.repository_id

    for run in range(4):
        _edit(sample_repo, f"edit-{run}")
        services.indexing.index(repository_id)

    status = services.status.status(repository_id)

    assert status.snapshot is not None
    assert status.file_count > 0
    assert status.symbol_count > 0


def test_a_failed_prune_does_not_fail_the_index(
    indexed: Registered, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot is already active by the time retention runs. Turning a
    housekeeping failure into a failed index would report a good snapshot as a
    bad one, and the next run would try to build it again."""
    services = indexed.services
    repository_id = indexed.repository_id
    services.indexing.index(repository_id)

    def explode(_: str) -> None:
        raise RuntimeError("retention is having a bad day")

    monkeypatch.setattr(services.recovery, "prune", explode)
    _edit(sample_repo, "after-failure")

    result = services.indexing.index(repository_id)

    assert result.snapshot.state is SnapshotState.ACTIVE
    assert "SNAPSHOT_RETENTION_FAILED" in result.warnings
