"""Chunks wired into the Phase 2 chunk tables, with cross-snapshot reuse."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from codeatlas.chunking.code_chunker import CodeChunker
from codeatlas.chunking.persist import persist_chunks
from codeatlas.domain.entities import Repository
from codeatlas.domain.enums import Language, SnapshotType
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.python.parser import PythonParser
from codeatlas.repositories.snapshot_manager import SnapshotManager
from codeatlas.storage.sqlite.database import Database
from codeatlas.storage.sqlite.models import ChunkVersionModel, LogicalChunkModel
from codeatlas.storage.sqlite.repositories import ChunkStore, RepositoryStore

_REL = "src/services/payment_service.py"
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "python_repo" / _REL


def _chunks(repo_id: str) -> list:
    source = _FIXTURE.read_text(encoding="utf-8")
    result = PythonParser().parse(ParseRequest(repo_id, _REL, Language.PYTHON, source.encode()))
    return CodeChunker().chunk(result, source, repo_id)


async def _seed_repo(db: Database, repo_id: str = "repo_x") -> Repository:
    repo = Repository(
        id=repo_id,
        name="x",
        root_path="/x",
        normalized_root_path=f"/{repo_id}",
        is_git_repository=False,
        created_at=datetime.now(UTC),
    )
    async with db.writer.transaction() as session:
        await RepositoryStore(session).upsert(repo)
    return repo


async def test_chunks_persist_and_reuse_across_snapshots(database: Database) -> None:
    repo = await _seed_repo(database)
    manager = SnapshotManager(database.writer)
    chunks = _chunks(repo.id)
    assert chunks

    snap_a = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await persist_chunks(database.writer, snap_a.id, chunks)
    await manager.begin_validation(snap_a.id)
    await manager.activate(snap_a.id)

    # Second snapshot, identical content -> chunk versions are reused, not duplicated.
    snap_b = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await persist_chunks(database.writer, snap_b.id, chunks)
    await manager.begin_validation(snap_b.id)
    await manager.activate(snap_b.id)

    unique_versions = {c.chunk_version_id for c in chunks}
    unique_logical = {c.logical_chunk_id for c in chunks}
    async with database.writer.read_session() as session:
        version_count = await session.scalar(select(func.count()).select_from(ChunkVersionModel))
        logical_count = await session.scalar(select(func.count()).select_from(LogicalChunkModel))
        active = await ChunkStore(session).active_chunk_versions(repo.id)

    assert version_count == len(unique_versions)
    assert logical_count == len(unique_logical)
    # Active scope resolves to the reused versions.
    assert {v.id for v in active} == unique_versions
