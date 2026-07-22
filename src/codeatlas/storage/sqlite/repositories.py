"""Data-access layer over the SQLite schema (Blueprint §4.7).

Each store operates on a provided :class:`AsyncSession` (writes come from the
coordinated writer). Stores translate explicitly between domain dataclasses and
ORM models. The chunk store exposes the active-scope query that enforces
snapshot filtering (CLAUDE.md §2.7): only chunk versions belonging to the
repository's ACTIVE snapshot via an active membership row are returned.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from codeatlas.domain.entities import (
    ChunkVersion,
    FileRecord,
    IndexJob,
    LogicalChunk,
    Repository,
    Snapshot,
)
from codeatlas.domain.enums import (
    FileClassification,
    IndexStatus,
    JobStatus,
    JobType,
    Language,
    ParseStatus,
    SnapshotStatus,
    SnapshotType,
)
from codeatlas.domain.identity import stable_hash
from codeatlas.parsing.contracts import ParseDiagnostic
from codeatlas.storage.sqlite.models import (
    ChunkVersionModel,
    FileModel,
    IndexJobModel,
    LogicalChunkModel,
    ParseDiagnosticModel,
    RepositoryModel,
    SnapshotChunkMembershipModel,
    SnapshotModel,
)

# --- Repository ---------------------------------------------------------------


class RepositoryStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, repository: Repository) -> None:
        existing = await self._session.get(RepositoryModel, repository.id)
        if existing is None:
            self._session.add(_repo_to_orm(repository))
            return
        existing.name = repository.name
        existing.root_path = repository.root_path
        existing.normalized_root_path = repository.normalized_root_path
        existing.is_git_repository = repository.is_git_repository
        existing.default_branch = repository.default_branch
        existing.last_indexed_at = repository.last_indexed_at

    async def get(self, repository_id: str) -> Repository | None:
        row = await self._session.get(RepositoryModel, repository_id)
        return _repo_from_orm(row) if row is not None else None


# --- Snapshot -----------------------------------------------------------------


class SnapshotStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, snapshot: Snapshot) -> None:
        self._session.add(_snapshot_to_orm(snapshot))

    async def get(self, snapshot_id: str) -> Snapshot | None:
        row = await self._session.get(SnapshotModel, snapshot_id)
        return _snapshot_from_orm(row) if row is not None else None

    async def get_active(self, repository_id: str) -> Snapshot | None:
        stmt = select(SnapshotModel).where(
            SnapshotModel.repository_id == repository_id,
            SnapshotModel.status == SnapshotStatus.ACTIVE.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _snapshot_from_orm(row) if row is not None else None

    async def set_status(self, snapshot_id: str, status: SnapshotStatus) -> None:
        await self._session.execute(
            update(SnapshotModel).where(SnapshotModel.id == snapshot_id).values(status=status.value)
        )

    async def update_fields(self, snapshot_id: str, **values: object) -> None:
        if values:
            await self._session.execute(
                update(SnapshotModel).where(SnapshotModel.id == snapshot_id).values(**values)
            )


# --- File ---------------------------------------------------------------------


class FileStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, files: list[FileRecord]) -> None:
        self._session.add_all([_file_to_orm(f) for f in files])

    async def list_for_snapshot(self, snapshot_id: str) -> list[FileRecord]:
        stmt = select(FileModel).where(FileModel.snapshot_id == snapshot_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_file_from_orm(row) for row in rows]


# --- Chunks (logical + versions + membership) ---------------------------------


class ChunkStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_logical(self, chunk: LogicalChunk) -> None:
        if await self._session.get(LogicalChunkModel, chunk.id) is None:
            self._session.add(_logical_to_orm(chunk))

    async def upsert_version(self, version: ChunkVersion) -> None:
        """Insert a chunk version if absent. Reuse (same id) is a no-op — the
        content-addressed id guarantees identical content maps to one row."""
        if await self._session.get(ChunkVersionModel, version.id) is None:
            self._session.add(_version_to_orm(version))

    async def add_membership(
        self, snapshot_id: str, chunk_version_id: str, *, is_active: bool = True
    ) -> None:
        existing = await self._session.get(
            SnapshotChunkMembershipModel, (snapshot_id, chunk_version_id)
        )
        if existing is None:
            self._session.add(
                SnapshotChunkMembershipModel(
                    snapshot_id=snapshot_id,
                    chunk_version_id=chunk_version_id,
                    is_active=is_active,
                )
            )
        else:
            existing.is_active = is_active

    async def version_exists(self, chunk_version_id: str) -> bool:
        return await self._session.get(ChunkVersionModel, chunk_version_id) is not None

    async def active_chunk_versions(self, repository_id: str) -> list[ChunkVersion]:
        """Chunk versions visible in the repository's ACTIVE snapshot only.

        Enforces snapshot filtering: staging/superseded snapshots and inactive
        membership rows are excluded (CLAUDE.md §2.7, §2.10).
        """
        stmt = (
            select(ChunkVersionModel)
            .join(
                SnapshotChunkMembershipModel,
                SnapshotChunkMembershipModel.chunk_version_id == ChunkVersionModel.id,
            )
            .join(
                SnapshotModel,
                SnapshotModel.id == SnapshotChunkMembershipModel.snapshot_id,
            )
            .where(
                SnapshotModel.repository_id == repository_id,
                SnapshotModel.status == SnapshotStatus.ACTIVE.value,
                SnapshotChunkMembershipModel.is_active.is_(True),
            )
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_version_from_orm(row) for row in rows]


# --- Index jobs ---------------------------------------------------------------


class JobStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: IndexJob) -> None:
        self._session.add(_job_to_orm(job))

    async def get(self, job_id: str) -> IndexJob | None:
        row = await self._session.get(IndexJobModel, job_id)
        return _job_from_orm(row) if row is not None else None

    async def set_status(self, job_id: str, status: JobStatus, *, error: str | None = None) -> None:
        values: dict[str, object] = {"status": status.value}
        if error is not None:
            values["error"] = error
        await self._session.execute(
            update(IndexJobModel).where(IndexJobModel.id == job_id).values(**values)
        )

    async def list_by_status(self, status: JobStatus) -> list[IndexJob]:
        stmt = select(IndexJobModel).where(IndexJobModel.status == status.value)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_job_from_orm(row) for row in rows]


# --- Parse diagnostics --------------------------------------------------------


class DiagnosticStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_for_file(
        self,
        *,
        repository_id: str,
        snapshot_id: str | None,
        relative_path: str,
        diagnostics: list[ParseDiagnostic],
        now: datetime | None = None,
    ) -> None:
        moment = now or datetime.now(UTC)
        for index, diagnostic in enumerate(diagnostics):
            self._session.add(
                ParseDiagnosticModel(
                    id=diagnostic_id(snapshot_id, relative_path, index),
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    relative_path=relative_path,
                    severity=diagnostic.severity,
                    message=diagnostic.message,
                    line=diagnostic.line,
                    detail=diagnostic.detail,
                    created_at=moment,
                )
            )

    async def list_for_snapshot(self, snapshot_id: str) -> list[ParseDiagnosticModel]:
        stmt = select(ParseDiagnosticModel).where(ParseDiagnosticModel.snapshot_id == snapshot_id)
        return list((await self._session.execute(stmt)).scalars().all())


def diagnostic_id(snapshot_id: str | None, relative_path: str, index: int) -> str:
    return "diag_" + stable_hash(snapshot_id, relative_path, index)


# --- Mapping helpers ----------------------------------------------------------


def _repo_to_orm(r: Repository) -> RepositoryModel:
    return RepositoryModel(
        id=r.id,
        name=r.name,
        root_path=r.root_path,
        normalized_root_path=r.normalized_root_path,
        is_git_repository=r.is_git_repository,
        default_branch=r.default_branch,
        created_at=r.created_at,
        last_indexed_at=r.last_indexed_at,
    )


def _repo_from_orm(m: RepositoryModel) -> Repository:
    return Repository(
        id=m.id,
        name=m.name,
        root_path=m.root_path,
        normalized_root_path=m.normalized_root_path,
        is_git_repository=m.is_git_repository,
        default_branch=m.default_branch,
        created_at=m.created_at,
        last_indexed_at=m.last_indexed_at,
    )


def _snapshot_to_orm(s: Snapshot) -> SnapshotModel:
    return SnapshotModel(
        id=s.id,
        repository_id=s.repository_id,
        snapshot_type=s.snapshot_type.value,
        status=s.status.value,
        deterministic_index_status=s.deterministic_index_status.value,
        semantic_index_status=s.semantic_index_status.value,
        semantic_coverage=s.semantic_coverage,
        pending_embedding_count=s.pending_embedding_count,
        active_embedding_namespace=s.active_embedding_namespace,
        branch=s.branch,
        commit_sha=s.commit_sha,
        working_tree_hash=s.working_tree_hash,
        parser_bundle_version=s.parser_bundle_version,
        chunker_version=s.chunker_version,
        retrieval_policy_version=s.retrieval_policy_version,
        created_at=s.created_at,
        activated_at=s.activated_at,
    )


def _snapshot_from_orm(m: SnapshotModel) -> Snapshot:
    return Snapshot(
        id=m.id,
        repository_id=m.repository_id,
        snapshot_type=SnapshotType(m.snapshot_type),
        status=SnapshotStatus(m.status),
        deterministic_index_status=IndexStatus(m.deterministic_index_status),
        semantic_index_status=IndexStatus(m.semantic_index_status),
        semantic_coverage=m.semantic_coverage,
        pending_embedding_count=m.pending_embedding_count,
        active_embedding_namespace=m.active_embedding_namespace,
        branch=m.branch,
        commit_sha=m.commit_sha,
        working_tree_hash=m.working_tree_hash,
        parser_bundle_version=m.parser_bundle_version,
        chunker_version=m.chunker_version,
        retrieval_policy_version=m.retrieval_policy_version,
        created_at=m.created_at,
        activated_at=m.activated_at,
    )


def _file_to_orm(f: FileRecord) -> FileModel:
    return FileModel(
        id=f.id,
        snapshot_id=f.snapshot_id,
        relative_path=f.relative_path,
        normalized_path=f.normalized_path,
        content_hash=f.content_hash,
        language=f.language.value if f.language else None,
        classification=f.classification.value,
        size_bytes=f.size_bytes,
        line_count=f.line_count,
        generated=f.generated,
        binary=f.binary,
        parse_status=f.parse_status.value,
    )


def _file_from_orm(m: FileModel) -> FileRecord:
    return FileRecord(
        id=m.id,
        snapshot_id=m.snapshot_id,
        relative_path=m.relative_path,
        normalized_path=m.normalized_path,
        content_hash=m.content_hash,
        classification=FileClassification(m.classification),
        language=Language(m.language) if m.language else None,
        size_bytes=m.size_bytes,
        line_count=m.line_count,
        generated=m.generated,
        binary=m.binary,
        parse_status=ParseStatus(m.parse_status),
    )


def _logical_to_orm(c: LogicalChunk) -> LogicalChunkModel:
    return LogicalChunkModel(
        id=c.id,
        repository_id=c.repository_id,
        normalized_path=c.normalized_path,
        qualified_name=c.qualified_name,
        chunk_role=c.chunk_role.value,
    )


def _version_to_orm(v: ChunkVersion) -> ChunkVersionModel:
    return ChunkVersionModel(
        id=v.id,
        logical_chunk_id=v.logical_chunk_id,
        content_hash=v.content_hash,
        parser_version=v.parser_version,
        chunker_version=v.chunker_version,
        start_line=v.start_line,
        end_line=v.end_line,
        raw_content=v.raw_content,
        retrieval_content=v.retrieval_content,
    )


def _version_from_orm(m: ChunkVersionModel) -> ChunkVersion:
    return ChunkVersion(
        id=m.id,
        logical_chunk_id=m.logical_chunk_id,
        content_hash=m.content_hash,
        parser_version=m.parser_version,
        chunker_version=m.chunker_version,
        start_line=m.start_line,
        end_line=m.end_line,
        raw_content=m.raw_content,
        retrieval_content=m.retrieval_content,
    )


def _job_to_orm(j: IndexJob) -> IndexJobModel:
    return IndexJobModel(
        id=j.id,
        repository_id=j.repository_id,
        snapshot_id=j.snapshot_id,
        job_type=j.job_type.value,
        status=j.status.value,
        attempts=j.attempts,
        error=j.error,
        cursor=j.cursor,
        created_at=j.created_at,
        updated_at=j.updated_at,
    )


def _job_from_orm(m: IndexJobModel) -> IndexJob:
    return IndexJob(
        id=m.id,
        repository_id=m.repository_id,
        job_type=JobType(m.job_type),
        status=JobStatus(m.status),
        snapshot_id=m.snapshot_id,
        attempts=m.attempts,
        error=m.error,
        cursor=m.cursor,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
