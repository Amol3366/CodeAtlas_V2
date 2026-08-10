"""Recovery from a hard kill, and the report it leaves behind.

The Phase 2 suite proves recovery from an *exception* raised inside ``index()``.
That path runs the ``except`` block, which closes the job row. A process that is
genuinely killed — power loss, ``taskkill /F``, an OOM kill — runs no Python at
all, so it leaves a different and worse state behind:

* a snapshot stuck in a build state (Phase 2 already heals this);
* an ``index_jobs`` row stuck at ``status='running'``, which nothing healed
  before P6-04, and which makes ``active_job_for`` report an index in progress
  **forever** — permanently blocking manual indexing, the watcher, and the
  reconciling scan alike;
* derived rows and FTS projections belonging to a snapshot that will never be
  activated.

Every test here starts from that state rather than from a raised exception.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.indexing import IndexResult
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.indexing.ownership import (
    PROCESS_TOKEN,
    owner_is_live,
    process_is_alive,
    process_start_time,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


def _dead_pid() -> int:
    """A pid that is certainly not running.

    Found by search rather than assumed: a hard-coded pid could be live on
    someone's machine, and the test would then assert the opposite of what it
    means.
    """
    for candidate in range(999_000, 1_000_000):
        if not process_is_alive(candidate):
            return candidate
    raise AssertionError("no dead pid could be found")


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


def _kill_mid_index(
    connection: sqlite3.Connection,
    repository_id: str,
    *,
    snapshot_id: str = "snap_killed",
    job_id: str = "job_killed",
    stage: str = "parsing",
) -> None:
    """Write the exact state a killed process leaves behind.

    A killed process cannot run cleanup, so both rows stay in the state the
    last completed write left them: the snapshot mid-build, the job running.
    """
    # Stamped *now*, because a kill happens after whatever indexed last. A
    # fixed past timestamp would make `latest_for` prefer the earlier success
    # and hide the interruption — which is correct behavior being fed a
    # situation that cannot occur.
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    connection.execute(
        "INSERT INTO snapshots (snapshot_id, repository_id, state, git_head,"
        " git_branch, git_dirty, working_tree_fingerprint, file_count,"
        " parsed_file_count, skipped_file_count, parse_error_count,"
        " parser_bundle_version, index_version, created_at, activated_at)"
        " VALUES (?, ?, ?, NULL, NULL, 0, 'fp', 0, 0, 0, 0, '1.0.0', '1.0.0',"
        " ?, NULL)",
        (snapshot_id, repository_id, stage, now),
    )
    connection.execute(
        "INSERT INTO index_jobs (job_id, repository_id, snapshot_id, stage,"
        " status, attempts, started_at, updated_at, diagnostics)"
        " VALUES (?, ?, ?, ?, 'running', 1, ?, ?, '[]')",
        (job_id, repository_id, snapshot_id, stage, now, now),
    )
    connection.commit()


# --- The defect: a dead job blocks indexing forever ------------------------


def test_a_killed_run_does_not_block_indexing_forever(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The regression this task exists for.

    Before P6-04 the stranded ``running`` job row survived recovery, so
    ``active_job_for`` kept reporting an index in progress and every later
    index attempt raised ``IndexInProgressError``. A repository killed once
    could never be indexed again — by hand, by the watcher, or by the
    reconciling scan — and went silently stale for good.
    """
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository_id = _register(Harness(services, connection), sample_repo)
        services.indexing.index(repository_id)
        _kill_mid_index(connection, repository_id)

    # A new process starts. Recovery runs during service construction.
    with connect(database) as connection:
        services = build_services(connection)
        result = services.indexing.index(repository_id)

    assert result.snapshot.state is SnapshotState.ACTIVE


def test_recovery_fails_the_stranded_job_row(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)

    harness.services.recovery.recover_interrupted()

    status = harness.connection.execute(
        "SELECT status FROM index_jobs WHERE job_id = 'job_killed'"
    ).fetchone()[0]
    assert status == "failed"


# --- Ownership: recovery must never heal a run that is still alive --------


def _claim(
    connection: sqlite3.Connection,
    job_id: str,
    pid: int,
    token: str,
    started_at: int | None = None,
) -> None:
    """Stamp a job with an owner, as `IndexJobStore.start` does.

    `started_at` is omitted from the stamp when `None`, which is exactly what
    `current_owner` does on a platform that cannot report a start time — and
    what every stamp written before ADR-0037 looks like.
    """
    owner: dict[str, object] = {"pid": pid, "token": token}
    if started_at is not None:
        owner["started_at"] = started_at
    connection.execute(
        "UPDATE index_jobs SET diagnostics = ? WHERE job_id = ?",
        (json.dumps({"owner": owner}), job_id),
    )
    connection.commit()


def test_recovery_leaves_this_process_s_own_running_index_alone(
    harness: Harness, sample_repo: Path
) -> None:
    """The race that recovery could previously lose.

    Recovery runs inside `build_services`, which is per request, and the
    watcher indexes on a background thread. Before ownership existed, a
    request arriving mid-index marked the live snapshot FAILED underneath the
    thread still building it.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id, job_id="job_live")
    _claim(harness.connection, "job_live", os.getpid(), PROCESS_TOKEN)

    report = harness.services.recovery.recover_interrupted()

    assert report.failed_job_ids == ()
    assert report.failed_snapshot_ids == ()
    live = harness.services.indexing.get_snapshot("snap_killed")
    assert live is not None
    assert live.state is not SnapshotState.FAILED


def test_recovery_leaves_another_live_process_s_index_alone(
    harness: Harness, sample_repo: Path
) -> None:
    """A second CodeAtlas process — a CLI index while the API serves.

    Its token differs, so the cheap in-process check does not apply and
    liveness decides. Conservative on purpose: an owner that still exists is
    left alone.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id, job_id="job_other")
    # A real, live pid that is not this process's token.
    _claim(harness.connection, "job_other", os.getpid(), "token-of-another-process")

    report = harness.services.recovery.recover_interrupted()

    assert report.failed_job_ids == ()


def test_recovery_strands_a_job_whose_owner_is_gone(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id, job_id="job_dead")
    _claim(harness.connection, "job_dead", _dead_pid(), "token-of-a-dead-process")

    report = harness.services.recovery.recover_interrupted()

    assert "job_dead" in report.failed_job_ids


def test_a_reused_pid_does_not_keep_a_dead_owner_alive() -> None:
    """The failure `ownership.py` has declared open since Phase 6.

    The OS reassigns a dead owner's pid, liveness says "alive", and the
    repository stays blocked from reindexing forever. A start time
    distinguishes a process *instance* from a pid, which is only a slot.

    Asserted against `owner_is_live` directly rather than through recovery,
    because the recovery-level version cannot be written honestly: it would
    need a live process whose pid matches a dead stamp, which is the very
    coincidence this prevents and cannot be arranged on demand.
    """
    owner = {
        "pid": os.getpid(),
        "token": "token-of-a-dead-process",
        # A valid FILETIME (1601-01-01) that no live process can hold.
        "started_at": 1,
    }

    assert owner_is_live(owner) is False


def test_a_matching_start_time_still_reports_the_owner_alive() -> None:
    """The conservative direction is preserved: a real owner is left alone.

    Without this, the implementation could be "return False whenever a start
    time is present", which satisfies the test above and corrupts a live
    index.
    """
    owner = {
        "pid": os.getpid(),
        "token": "token-of-another-process",
        "started_at": process_start_time(os.getpid()),
    }

    assert owner_is_live(owner) is True


def test_a_stamp_without_a_start_time_keeps_the_old_behaviour() -> None:
    """A database written by an earlier build must not change meaning.

    Those stamps carry no `started_at` and one cannot be inferred, so the
    rule stays pid-only for them — what they were written under.
    """
    owner = {"pid": os.getpid(), "token": "token-of-another-process"}

    assert owner_is_live(owner) is True


def test_an_unreadable_start_time_does_not_strand_a_live_run() -> None:
    """`None` means unknown, and unknown must read as alive.

    Treating it as "dead" would let one process heal another's in-flight
    index, which is the corruption this module exists to prevent.
    """
    owner = {
        "pid": os.getpid(),
        "token": "token-of-another-process",
        "started_at": None,
    }

    assert owner_is_live(owner) is True


def test_recovery_strands_a_run_whose_owner_s_pid_was_reused(
    harness: Harness, sample_repo: Path
) -> None:
    """The same rule, proven where a user actually feels it.

    A stamp carrying a live pid with the wrong start time is a reused slot.
    Before this, `recover_interrupted` left the job alone and the repository
    could never reindex.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id, job_id="job_reused")
    _claim(
        harness.connection,
        "job_reused",
        os.getpid(),
        "token-of-a-dead-process",
        started_at=1,
    )

    report = harness.services.recovery.recover_interrupted()

    assert "job_reused" in report.failed_job_ids


def test_an_unclaimed_job_is_stranded(
    harness: Harness, sample_repo: Path
) -> None:
    """A row from before ownership existed, or from a database upgraded in.

    Nobody is claiming it, so nobody is harmed by healing it — and leaving it
    is what blocks indexing forever.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id, job_id="job_legacy")

    report = harness.services.recovery.recover_interrupted()

    assert "job_legacy" in report.failed_job_ids


def test_a_live_index_is_not_disturbed_by_concurrent_service_construction(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The defect, end to end, with real threads.

    One thread indexes; the other builds services repeatedly, as an arriving
    request would. The index must complete and activate.
    """
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        repository_id = repository.repository_id

    indexed: list[IndexResult] = []
    failures: list[BaseException] = []
    stop = threading.Event()

    def index_it() -> None:
        try:
            with connect(database) as connection:
                services = build_services(connection)
                indexed.append(services.indexing.index(repository_id))
        except BaseException as error:  # reported, never swallowed
            failures.append(error)
        finally:
            stop.set()

    def keep_building() -> None:
        while not stop.is_set():
            with connect(database) as connection:
                build_services(connection)

    indexer = threading.Thread(target=index_it)
    requester = threading.Thread(target=keep_building)
    indexer.start()
    requester.start()
    indexer.join(timeout=120)
    requester.join(timeout=10)

    assert not failures, f"the index failed: {failures[0]!r}"
    assert indexed, "the indexing thread produced no outcome"
    assert indexed[0].snapshot.state is SnapshotState.ACTIVE


# --- "Says what it recovered" ---------------------------------------------


def test_diagnostics_report_the_interrupted_run(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id, stage="chunking")

    harness.services.recovery.recover_interrupted()
    diagnostics = harness.services.status.diagnostics(repository_id)

    assert diagnostics.interrupted_run is not None
    assert diagnostics.interrupted_run.snapshot_id == "snap_killed"
    assert diagnostics.interrupted_run.stage == "chunking"
    assert "INDEX_RUN_INTERRUPTED" in diagnostics.warnings


def test_a_never_indexed_repository_is_distinguishable(
    harness: Harness, sample_repo: Path
) -> None:
    """The distinction ADR-0007 decision 3 exists for: the remedies differ."""
    repository_id = _register(harness, sample_repo)

    diagnostics = harness.services.status.diagnostics(repository_id)

    assert diagnostics.interrupted_run is None
    assert diagnostics.snapshot_id is None
    assert "INDEX_RUN_INTERRUPTED" not in diagnostics.warnings


def test_the_report_survives_the_process_that_wrote_it(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Recovery runs per request; only the first one finds anything.

    If the fact were held in memory it would belong to whichever request
    happened to construct services first and be gone by the time anyone asked.
    """
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository_id = _register(Harness(services, connection), sample_repo)
        services.indexing.index(repository_id)
        _kill_mid_index(connection, repository_id)

    with connect(database) as connection:
        build_services(connection)  # heals

    with connect(database) as connection:  # a later, unrelated request
        services = build_services(connection)
        diagnostics = services.status.diagnostics(repository_id)

    assert diagnostics.interrupted_run is not None
    assert diagnostics.interrupted_run.snapshot_id == "snap_killed"


def test_a_successful_reindex_clears_the_interrupted_report(
    harness: Harness, sample_repo: Path
) -> None:
    """The report describes a live condition, not a permanent scar.

    Once the repository has been indexed successfully, its last index was not
    interrupted, and saying otherwise would be false.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)
    harness.services.recovery.recover_interrupted()

    harness.services.indexing.index(repository_id)
    diagnostics = harness.services.status.diagnostics(repository_id)

    assert diagnostics.interrupted_run is None
    assert "INDEX_RUN_INTERRUPTED" not in diagnostics.warnings


def test_recovery_is_idempotent(harness: Harness, sample_repo: Path) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)

    first = harness.services.recovery.recover_interrupted()
    second = harness.services.recovery.recover_interrupted()

    assert first.failed_snapshot_ids == ("snap_killed",)
    assert second.failed_snapshot_ids == ()
    assert second.failed_job_ids == ()


# --- "With no orphaned rows" ----------------------------------------------


def _snapshot_scoped_tables(connection: sqlite3.Connection) -> list[str]:
    """Tables whose rows belong to a snapshot and would cascade with it.

    Derived generically rather than listed, so a future migration that adds a
    snapshot-scoped table is covered by this test without anyone remembering
    to update it. Tables that hold a snapshot id as *historical data* — change
    analyses, messages — declare no such foreign key and are correctly absent:
    a message must keep naming the snapshot that answered it.
    """
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    ]
    scoped = []
    for table in tables:
        keys = connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()
        if any(key["table"] == "snapshots" for key in keys):
            scoped.append(table)
    return scoped


def test_recovery_leaves_no_rows_behind_for_the_dead_snapshot(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    good = harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)

    # Give the dead snapshot derived rows, as a real killed run would have.
    harness.connection.execute(
        "INSERT INTO files (snapshot_id, file_id, relative_path, display_path,"
        " content_hash, size_bytes, line_count, language, classification)"
        " SELECT 'snap_killed', file_id, relative_path, display_path,"
        " content_hash, size_bytes, line_count, language, classification"
        " FROM files WHERE snapshot_id = ?",
        (good.snapshot.snapshot_id,),
    )
    harness.connection.commit()

    harness.services.recovery.recover_interrupted()

    for table in _snapshot_scoped_tables(harness.connection):
        remaining = harness.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE snapshot_id = 'snap_killed'"
        ).fetchone()[0]
        assert remaining == 0, f"{table} kept rows for the recovered snapshot"


def test_recovery_clears_the_fts_projections_no_cascade_can_reach(
    harness: Harness, sample_repo: Path
) -> None:
    """FTS5 virtual tables have no foreign keys, so nothing cascades to them.

    A search projection left behind by a killed run is the one orphan that
    could actually surface in a result.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)
    harness.connection.execute(
        "INSERT INTO file_search (file_id, snapshot_id, file_path)"
        " VALUES ('f1', 'snap_killed', 'a.py')"
    )
    harness.connection.commit()

    harness.services.recovery.recover_interrupted()

    remaining = harness.connection.execute(
        "SELECT COUNT(*) FROM file_search WHERE snapshot_id = 'snap_killed'"
    ).fetchone()[0]
    assert remaining == 0


def test_recovery_keeps_the_snapshot_row_that_names_what_failed(
    harness: Harness, sample_repo: Path
) -> None:
    """Derived rows go; the snapshot row stays, because it is the record."""
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)

    harness.services.recovery.recover_interrupted()

    snapshot = harness.services.indexing.get_snapshot("snap_killed")
    assert snapshot is not None
    assert snapshot.state is SnapshotState.FAILED


def test_recovery_never_touches_the_active_snapshot(
    harness: Harness, sample_repo: Path
) -> None:
    """The invariant every recovery path is measured against."""
    repository_id = _register(harness, sample_repo)
    good = harness.services.indexing.index(repository_id)
    _kill_mid_index(harness.connection, repository_id)

    harness.services.recovery.recover_interrupted()

    active = harness.services.indexing.get_active_snapshot(repository_id)
    assert active is not None
    assert active.snapshot_id == good.snapshot.snapshot_id

    files = harness.connection.execute(
        "SELECT COUNT(*) FROM files WHERE snapshot_id = ?",
        (good.snapshot.snapshot_id,),
    ).fetchone()[0]
    assert files > 0
