"""Index job service and crash recovery (Blueprint §4.10, CLAUDE.md §2.12).

Jobs move PENDING -> RUNNING -> COMPLETED/FAILED. On startup, recovery brings the
store to a safe state: any job left RUNNING by a crash returns to PENDING (so it
can be retried), and any snapshot left half-built (STAGING/VALIDATING) is FAILED
so it can never leak into active-scope queries (CLAUDE.md §2.10).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import update

from codeatlas.domain.entities import IndexJob
from codeatlas.domain.enums import JobStatus, JobType, SnapshotStatus
from codeatlas.storage.sqlite.models import IndexJobModel, SnapshotModel
from codeatlas.storage.sqlite.repositories import JobStore
from codeatlas.storage.sqlite.writer import CoordinatedWriter


@dataclass(frozen=True)
class RecoveryReport:
    """Outcome of a startup recovery pass."""

    jobs_requeued: int
    snapshots_failed: int


def _new_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


class JobService:
    def __init__(self, writer: CoordinatedWriter) -> None:
        self._writer = writer

    async def create(
        self,
        repository_id: str,
        *,
        job_type: JobType,
        snapshot_id: str | None = None,
        now: datetime | None = None,
    ) -> IndexJob:
        moment = now or datetime.now(UTC)
        job = IndexJob(
            id=_new_job_id(),
            repository_id=repository_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            snapshot_id=snapshot_id,
            created_at=moment,
            updated_at=moment,
        )
        async with self._writer.transaction() as session:
            await JobStore(session).add(job)
        return job

    async def mark_running(self, job_id: str) -> None:
        await self._set_status(job_id, JobStatus.RUNNING)

    async def mark_completed(self, job_id: str) -> None:
        await self._set_status(job_id, JobStatus.COMPLETED)

    async def mark_failed(self, job_id: str, error: str) -> None:
        await self._set_status(job_id, JobStatus.FAILED, error=error)

    async def _set_status(
        self, job_id: str, status: JobStatus, *, error: str | None = None
    ) -> None:
        async with self._writer.transaction() as session:
            await JobStore(session).set_status(job_id, status, error=error)
            await session.execute(
                update(IndexJobModel)
                .where(IndexJobModel.id == job_id)
                .values(updated_at=datetime.now(UTC))
            )

    async def recover(self, *, now: datetime | None = None) -> RecoveryReport:
        """Bring jobs/snapshots to a safe state after an unclean shutdown."""
        moment = now or datetime.now(UTC)
        async with self._writer.transaction() as session:
            job_result = await session.execute(
                update(IndexJobModel)
                .where(IndexJobModel.status == JobStatus.RUNNING.value)
                .values(
                    status=JobStatus.PENDING.value,
                    attempts=IndexJobModel.attempts + 1,
                    updated_at=moment,
                )
            )
            snapshot_result = await session.execute(
                update(SnapshotModel)
                .where(
                    SnapshotModel.status.in_(
                        [SnapshotStatus.STAGING.value, SnapshotStatus.VALIDATING.value]
                    )
                )
                .values(status=SnapshotStatus.FAILED.value)
            )
        return RecoveryReport(
            jobs_requeued=_rowcount(job_result),
            snapshots_failed=_rowcount(snapshot_result),
        )


def _rowcount(result: object) -> int:
    """Rows affected by a DML statement (CursorResult.rowcount), safely typed."""
    return int(getattr(result, "rowcount", 0) or 0)
