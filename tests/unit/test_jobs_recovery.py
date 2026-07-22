"""Crash-recovery tests for index jobs and half-built snapshots (Blueprint §4.10).

Exit criterion: interrupted jobs recover safely on restart, and staging snapshots
never leak into active scope.
"""

from __future__ import annotations

from datetime import UTC, datetime

from codeatlas.domain.entities import Repository
from codeatlas.domain.enums import JobStatus, JobType, SnapshotStatus, SnapshotType
from codeatlas.indexing.jobs import JobService
from codeatlas.repositories.snapshot_manager import SnapshotManager
from codeatlas.storage.sqlite.database import Database
from codeatlas.storage.sqlite.repositories import JobStore, RepositoryStore, SnapshotStore


async def _seed_repo(db: Database) -> Repository:
    repo = Repository(
        id="repo_x",
        name="x",
        root_path="/x",
        normalized_root_path="/x",
        is_git_repository=False,
        created_at=datetime.now(UTC),
    )
    async with db.writer.transaction() as session:
        await RepositoryStore(session).upsert(repo)
    return repo


async def test_recovery_requeues_running_jobs_and_fails_half_built_snapshots(
    database: Database,
) -> None:
    repo = await _seed_repo(database)
    jobs = JobService(database.writer)
    manager = SnapshotManager(database.writer)

    # Simulate a crash mid-index: a RUNNING job, a STAGING and a VALIDATING snapshot,
    # plus one fully-activated snapshot that must survive recovery untouched.
    running_job = await jobs.create(repo.id, job_type=JobType.FULL_INDEX)
    await jobs.mark_running(running_job.id)

    staging = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    validating = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await manager.begin_validation(validating.id)
    active = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await manager.begin_validation(active.id)
    await manager.activate(active.id)

    report = await jobs.recover()

    assert report.jobs_requeued == 1
    assert report.snapshots_failed == 2  # staging + validating

    async with database.writer.read_session() as session:
        job = await JobStore(session).get(running_job.id)
        snaps = SnapshotStore(session)
        staging_after = await snaps.get(staging.id)
        validating_after = await snaps.get(validating.id)
        active_after = await snaps.get_active(repo.id)

    assert job is not None
    assert job.status is JobStatus.PENDING
    assert job.attempts == 1
    assert staging_after is not None and staging_after.status is SnapshotStatus.FAILED
    assert validating_after is not None and validating_after.status is SnapshotStatus.FAILED
    # The activated snapshot is untouched (activation is atomic; it fully committed).
    assert active_after is not None and active_after.id == active.id


async def test_recovery_is_idempotent(database: Database) -> None:
    await _seed_repo(database)
    jobs = JobService(database.writer)
    first = await jobs.recover()
    second = await jobs.recover()
    assert first.jobs_requeued == 0 and first.snapshots_failed == 0
    assert second.jobs_requeued == 0 and second.snapshots_failed == 0
