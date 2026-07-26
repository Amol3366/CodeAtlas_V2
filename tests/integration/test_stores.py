"""Store behavior against real SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.contracts import SymbolKind
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import (
    FileStore,
    IndexJobStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)

CREATED_AT = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 7, 25, 13, 0, 0, tzinfo=UTC)
LATEST = datetime(2026, 7, 25, 14, 0, 0, tzinfo=UTC)


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "db.sqlite") as open_connection:
        apply_migrations(open_connection)
        yield open_connection


def _repository(repository_id: str = "repo_1") -> Repository:
    return Repository(
        repository_id=repository_id,
        display_name="demo",
        canonical_root=f"C:/repos/{repository_id}",
        created_at=CREATED_AT,
    )


def _snapshot(
    snapshot_id: str = "snap_1",
    repository_id: str = "repo_1",
    state: SnapshotState = SnapshotState.PARSING,
) -> Snapshot:
    return Snapshot(
        snapshot_id=snapshot_id,
        repository_id=repository_id,
        state=state,
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


def _file(file_id: str = "file_1", relative_path: str = "src/a.py") -> FileRecord:
    return FileRecord(
        file_id=file_id,
        relative_path=relative_path,
        display_path=relative_path,
        content_hash="hash",
        size_bytes=10,
        line_count=8,
        language="python",
        classification=FileClassification.SOURCE_CODE,
    )


def _symbol(
    symbol_id: str,
    name: str,
    qualified_name: str,
    kind: SymbolKind = SymbolKind.METHOD,
    file_id: str = "file_1",
    start_line: int = 1,
) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        symbol_version_id=f"symv_{symbol_id}",
        file_id=file_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        module_path="src.a",
        signature=None,
        start_line=start_line,
        end_line=start_line + 1,
        start_byte=0,
        end_byte=10,
        content_hash="hash",
        visibility="public",
    )


def test_repository_round_trips_by_id_and_root(connection: sqlite3.Connection) -> None:
    store = RepositoryStore(connection)
    store.add(_repository())
    stored = store.get("repo_1")
    assert stored is not None
    assert stored.display_name == "demo"
    assert stored.created_at == CREATED_AT
    assert store.get_by_root("C:/repos/repo_1") is not None
    assert store.get("missing") is None


def test_repository_list_is_ordered_by_display_name(
    connection: sqlite3.Connection,
) -> None:
    store = RepositoryStore(connection)
    store.add(_repository("repo_b"))
    store.add(_repository("repo_a"))
    names = [item.repository_id for item in store.list_all()]
    assert names == ["repo_a", "repo_b"]


def test_staging_snapshot_is_not_active(connection: sqlite3.Connection) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot())
    assert snapshots.get_active("repo_1") is None
    stored = snapshots.get("snap_1")
    assert stored is not None
    assert stored.state is SnapshotState.PARSING


def test_activation_supersedes_the_previous_active_snapshot(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1"))
    snapshots.activate("snap_1", CREATED_AT)
    snapshots.add_staging(_snapshot("snap_2"))
    snapshots.activate("snap_2", CREATED_AT)

    active = snapshots.get_active("repo_1")
    assert active is not None
    assert active.snapshot_id == "snap_2"
    assert active.activated_at == CREATED_AT
    superseded = snapshots.get("snap_1")
    assert superseded is not None
    assert superseded.state is SnapshotState.SUPERSEDED


def test_set_state_records_failure(connection: sqlite3.Connection) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot())
    snapshots.set_state("snap_1", SnapshotState.FAILED)
    stored = snapshots.get("snap_1")
    assert stored is not None
    assert stored.state is SnapshotState.FAILED
    assert snapshots.get_active("repo_1") is None


def test_most_recent_superseded_prefers_the_newest_activation(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    for snapshot_id, activated_at in (
        ("snap_1", CREATED_AT),
        ("snap_2", LATER),
        ("snap_3", LATEST),
    ):
        snapshots.add_staging(_snapshot(snapshot_id))
        snapshots.activate(snapshot_id, activated_at)

    target = snapshots.most_recent_superseded("repo_1")
    assert target is not None
    assert target.snapshot_id == "snap_2"


def test_most_recent_superseded_is_none_without_a_target(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1"))
    snapshots.activate("snap_1", CREATED_AT)
    assert snapshots.most_recent_superseded("repo_1") is None


def test_rollback_swaps_active_and_the_newest_superseded(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1"))
    snapshots.activate("snap_1", CREATED_AT)
    snapshots.add_staging(_snapshot("snap_2"))
    snapshots.activate("snap_2", LATER)

    restored_id = snapshots.rollback("repo_1", LATEST)

    assert restored_id == "snap_1"
    active = snapshots.get_active("repo_1")
    assert active is not None
    assert active.snapshot_id == "snap_1"
    assert active.activated_at == LATEST
    demoted = snapshots.get("snap_2")
    assert demoted is not None
    assert demoted.state is SnapshotState.SUPERSEDED


def test_rollback_without_a_target_raises(connection: sqlite3.Connection) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1"))
    snapshots.activate("snap_1", CREATED_AT)
    with pytest.raises(LookupError):
        snapshots.rollback("repo_1", LATER)


def test_list_for_repository_is_scoped_to_one_repository(
    connection: sqlite3.Connection,
) -> None:
    repositories = RepositoryStore(connection)
    repositories.add(_repository("repo_1"))
    repositories.add(_repository("repo_2"))
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1", "repo_1"))
    snapshots.add_staging(_snapshot("snap_2", "repo_1"))
    snapshots.add_staging(_snapshot("snap_other", "repo_2"))

    listed = [item.snapshot_id for item in snapshots.list_for_repository("repo_1")]
    assert listed == ["snap_2", "snap_1"]


def test_list_by_states_filters_by_state_and_repository(
    connection: sqlite3.Connection,
) -> None:
    repositories = RepositoryStore(connection)
    repositories.add(_repository("repo_1"))
    repositories.add(_repository("repo_2"))
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_parsing", "repo_1"))
    snapshots.add_staging(_snapshot("snap_failed", "repo_1"))
    snapshots.set_state("snap_failed", SnapshotState.FAILED)
    snapshots.add_staging(_snapshot("snap_other", "repo_2"))

    everywhere = {
        item.snapshot_id
        for item in snapshots.list_by_states([SnapshotState.PARSING])
    }
    assert everywhere == {"snap_parsing", "snap_other"}

    scoped = {
        item.snapshot_id
        for item in snapshots.list_by_states(
            [SnapshotState.PARSING, SnapshotState.FAILED], "repo_1"
        )
    }
    assert scoped == {"snap_parsing", "snap_failed"}


def test_deleting_a_snapshot_cascades_to_its_files_and_symbols(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1"))
    FileStore(connection).add_many("snap_1", [_file()])
    SymbolStore(connection).add_many("snap_1", [_symbol("sym_1", "run", "A.run")])

    snapshots.delete("snap_1")

    assert snapshots.get("snap_1") is None
    assert FileStore(connection).list_for_snapshot("snap_1") == ()
    assert SymbolStore(connection).count_for_snapshot("snap_1") == 0


def test_deleting_an_unknown_snapshot_is_a_no_op(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    snapshots = SnapshotStore(connection)
    snapshots.add_staging(_snapshot("snap_1"))
    snapshots.delete("snap_missing")
    assert snapshots.get("snap_1") is not None


def test_files_round_trip_and_are_scoped_to_a_snapshot(
    connection: sqlite3.Connection,
) -> None:
    RepositoryStore(connection).add(_repository())
    SnapshotStore(connection).add_staging(_snapshot())
    files = FileStore(connection)
    files.add_many("snap_1", [_file(), _file("file_2", "src/b.py")])

    stored = files.list_for_snapshot("snap_1")
    assert [item.relative_path for item in stored] == ["src/a.py", "src/b.py"]
    assert stored[0].classification is FileClassification.SOURCE_CODE
    assert files.get("snap_1", "file_1") is not None
    assert files.get("snap_other", "file_1") is None


def _seed_symbols(connection: sqlite3.Connection) -> SymbolStore:
    RepositoryStore(connection).add(_repository())
    SnapshotStore(connection).add_staging(_snapshot())
    FileStore(connection).add_many("snap_1", [_file()])
    symbols = SymbolStore(connection)
    symbols.add_many(
        "snap_1",
        [
            _symbol("sym_1", "PaymentService", "PaymentService", SymbolKind.CLASS),
            _symbol("sym_2", "capture", "PaymentService.capture", start_line=7),
            _symbol("sym_3", "other", "Other.capture", start_line=20),
        ],
    )
    return symbols


def test_find_exact_prefers_the_qualified_name(connection: sqlite3.Connection) -> None:
    symbols = _seed_symbols(connection)
    found = symbols.find_exact("snap_1", "PaymentService.capture", limit=10)
    assert [item.symbol_id for item in found] == ["sym_2"]


def test_find_exact_falls_back_to_the_module_qualified_name(
    connection: sqlite3.Connection,
) -> None:
    symbols = _seed_symbols(connection)
    found = symbols.find_exact("snap_1", "src.a.PaymentService.capture", limit=10)
    assert [item.symbol_id for item in found] == ["sym_2"]


def test_find_exact_falls_back_to_the_bare_name(
    connection: sqlite3.Connection,
) -> None:
    symbols = _seed_symbols(connection)
    found = symbols.find_exact("snap_1", "capture", limit=10)
    assert [item.symbol_id for item in found] == ["sym_2"]


def test_find_exact_is_case_insensitive_as_a_last_resort(
    connection: sqlite3.Connection,
) -> None:
    symbols = _seed_symbols(connection)
    found = symbols.find_exact("snap_1", "CAPTURE", limit=10)
    assert [item.symbol_id for item in found] == ["sym_2"]


def test_find_exact_returns_nothing_for_an_unknown_symbol(
    connection: sqlite3.Connection,
) -> None:
    symbols = _seed_symbols(connection)
    assert symbols.find_exact("snap_1", "NoSuchSymbol", limit=10) == ()


def test_find_exact_respects_the_limit_and_snapshot_scope(
    connection: sqlite3.Connection,
) -> None:
    symbols = _seed_symbols(connection)
    assert len(symbols.find_exact("snap_1", "capture", limit=1)) == 1
    assert symbols.find_exact("snap_other", "capture", limit=10) == ()
    assert symbols.count_for_snapshot("snap_1") == 3


def test_index_job_lifecycle(connection: sqlite3.Connection) -> None:
    RepositoryStore(connection).add(_repository())
    jobs = IndexJobStore(connection, clock=lambda: CREATED_AT)
    jobs.start("job_1", "repo_1", "snap_1")
    assert jobs.active_job_for("repo_1") == "job_1"

    jobs.update_stage("job_1", "parsing", "running")
    assert jobs.active_job_for("repo_1") == "job_1"

    jobs.finish(
        "job_1",
        "succeeded",
        {"outcome": "activated", "skipped_by_reason": {"BINARY": 2}},
    )
    assert jobs.active_job_for("repo_1") is None

    latest = jobs.latest_for("repo_1")
    assert latest is not None
    assert latest["skipped_by_reason"] == {"BINARY": 2}
