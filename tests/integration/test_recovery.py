"""Snapshot rollback, crash recovery, and retention."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.recovery import NON_TERMINAL_STATES
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import NoRollbackTargetError, RepositoryNotFoundError
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[Harness]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        yield Harness(services=build_services(connection), connection=connection)


def _register(harness: Harness, root: Path) -> str:
    repository = harness.services.registration.register(
        RegisterRepositoryRequest(path=str(root))
    )
    return repository.repository_id


_EDIT_COUNTER = [0]


def _edit(root: Path) -> None:
    """Append a distinct method so the working-tree fingerprint changes."""
    _EDIT_COUNTER[0] += 1
    index = _EDIT_COUNTER[0]
    path = root / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + f"\n    def variant_{index}(self) -> int:\n        return {index}\n",
        encoding="utf-8",
    )


def _insert_interrupted(
    connection: sqlite3.Connection,
    repository_id: str,
    snapshot_id: str,
    state: str,
) -> None:
    connection.execute(
        "INSERT INTO snapshots (snapshot_id, repository_id, state, git_head,"
        " git_branch, git_dirty, working_tree_fingerprint, file_count,"
        " parsed_file_count, skipped_file_count, parse_error_count,"
        " parser_bundle_version, index_version, created_at, activated_at)"
        " VALUES (?, ?, ?, NULL, NULL, 0, 'fp', 0, 0, 0, 0, '1.0.0', '1.0.0',"
        " '2026-07-25T00:00:00Z', NULL)",
        (snapshot_id, repository_id, state),
    )


def test_rollback_restores_the_previous_snapshot(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    first = harness.services.indexing.index(repository_id)
    _edit(sample_repo)
    second = harness.services.indexing.index(repository_id)

    restored = harness.services.recovery.rollback(repository_id)

    assert restored.snapshot_id == first.snapshot.snapshot_id
    assert restored.state is SnapshotState.ACTIVE
    superseded = harness.services.indexing.get_snapshot(second.snapshot.snapshot_id)
    assert superseded is not None
    assert superseded.state is SnapshotState.SUPERSEDED


def test_rollback_refreshes_the_activation_timestamp(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    first = harness.services.indexing.index(repository_id)
    _edit(sample_repo)
    harness.services.indexing.index(repository_id)

    restored = harness.services.recovery.rollback(repository_id)
    assert restored.activated_at is not None
    assert first.snapshot.activated_at is not None
    assert restored.activated_at >= first.snapshot.activated_at


def test_rollback_without_a_target_raises(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    with pytest.raises(NoRollbackTargetError):
        harness.services.recovery.rollback(repository_id)


def test_rollback_for_an_unknown_repository_raises(harness: Harness) -> None:
    with pytest.raises(RepositoryNotFoundError):
        harness.services.recovery.rollback("repo_missing")


def test_rollback_never_creates_two_active_snapshots(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _edit(sample_repo)
    harness.services.indexing.index(repository_id)
    harness.services.recovery.rollback(repository_id)

    count = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE state = 'active'"
    ).fetchone()[0]
    assert count == 1


def test_rollback_makes_search_results_revert(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    (sample_repo / "src" / "payments" / "extra.py").write_text(
        "class OnlyInSecond:\n    pass\n", encoding="utf-8"
    )
    harness.services.indexing.index(repository_id)

    from codeatlas.application.lookup import SymbolLookupRequest

    before = harness.services.lookup.lookup(
        SymbolLookupRequest(repository_id, "OnlyInSecond", "req-1")
    )
    assert before.evidence

    harness.services.recovery.rollback(repository_id)

    after = harness.services.lookup.lookup(
        SymbolLookupRequest(repository_id, "OnlyInSecond", "req-2")
    )
    assert after.evidence == []
    assert "NO_EXACT_SYMBOL_MATCH" in after.warnings


@pytest.mark.parametrize("state", sorted(item.value for item in NON_TERMINAL_STATES))
def test_interrupted_snapshot_is_failed_on_recovery(
    harness: Harness, sample_repo: Path, state: str
) -> None:
    repository_id = _register(harness, sample_repo)
    good = harness.services.indexing.index(repository_id)
    _insert_interrupted(harness.connection, repository_id, "snap_crashed", state)

    report = harness.services.recovery.recover_interrupted()

    assert "snap_crashed" in report.failed_snapshot_ids
    crashed = harness.services.indexing.get_snapshot("snap_crashed")
    assert crashed is not None
    assert crashed.state is SnapshotState.FAILED

    active = harness.services.indexing.get_active_snapshot(repository_id)
    assert active is not None
    assert active.snapshot_id == good.snapshot.snapshot_id


def test_recovery_never_touches_active_or_superseded_snapshots(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    first = harness.services.indexing.index(repository_id)
    _edit(sample_repo)
    second = harness.services.indexing.index(repository_id)

    report = harness.services.recovery.recover_interrupted()

    assert report.failed_snapshot_ids == ()
    newest = harness.services.indexing.get_snapshot(second.snapshot.snapshot_id)
    oldest = harness.services.indexing.get_snapshot(first.snapshot.snapshot_id)
    assert newest is not None
    assert oldest is not None
    assert newest.state is SnapshotState.ACTIVE
    assert oldest.state is SnapshotState.SUPERSEDED


def test_building_services_recovers_a_crashed_snapshot(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        _insert_interrupted(
            connection, repository.repository_id, "snap_crashed", "indexing"
        )

    # A fresh process constructing services must heal the crashed predecessor.
    with connect(database) as connection:
        services = build_services(connection)
        crashed = services.indexing.get_snapshot("snap_crashed")

    assert crashed is not None
    assert crashed.state is SnapshotState.FAILED


def test_prune_keeps_the_active_and_one_superseded_snapshot(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    for _ in range(3):
        harness.services.indexing.index(repository_id)
        _edit(sample_repo)
    harness.services.indexing.index(repository_id)

    report = harness.services.recovery.prune(repository_id)

    remaining = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE repository_id = ?",
        (repository_id,),
    ).fetchone()[0]
    assert remaining == 2
    assert report.deleted_snapshot_ids


def test_prune_never_deletes_the_active_snapshot(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    for _ in range(2):
        harness.services.indexing.index(repository_id)
        _edit(sample_repo)
    active_before = harness.services.indexing.get_active_snapshot(repository_id)

    harness.services.recovery.prune(repository_id)

    active_after = harness.services.indexing.get_active_snapshot(repository_id)
    assert active_before is not None
    assert active_after is not None
    assert active_after.snapshot_id == active_before.snapshot_id


def test_prune_leaves_a_rollback_target(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    for _ in range(3):
        harness.services.indexing.index(repository_id)
        _edit(sample_repo)
    harness.services.indexing.index(repository_id)

    harness.services.recovery.prune(repository_id)
    restored = harness.services.recovery.rollback(repository_id)

    assert restored.state is SnapshotState.ACTIVE


def test_prune_removes_failed_snapshots(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _insert_interrupted(harness.connection, repository_id, "snap_bad", "failed")

    harness.services.recovery.prune(repository_id)

    assert harness.services.indexing.get_snapshot("snap_bad") is None


def test_prune_cascades_to_derived_rows(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    for _ in range(3):
        harness.services.indexing.index(repository_id)
        _edit(sample_repo)
    harness.services.indexing.index(repository_id)

    harness.services.recovery.prune(repository_id)

    orphan_files = harness.connection.execute(
        "SELECT COUNT(*) FROM files WHERE snapshot_id NOT IN"
        " (SELECT snapshot_id FROM snapshots)"
    ).fetchone()[0]
    orphan_symbols = harness.connection.execute(
        "SELECT COUNT(*) FROM symbols WHERE snapshot_id NOT IN"
        " (SELECT snapshot_id FROM snapshots)"
    ).fetchone()[0]
    assert orphan_files == 0
    assert orphan_symbols == 0
