"""Storage + snapshot tests: pragmas, staging isolation, chunk reuse, deletion.

Covers Phase 2 exit criteria (CLAUDE.md §9):
- staging snapshot data provably cannot appear in active-scope queries;
- unchanged content hash reused across two snapshots (same chunk_version_id);
- deleted content absent from active membership after re-scan.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from codeatlas.domain.entities import ChunkVersion, LogicalChunk, Repository
from codeatlas.domain.enums import ChunkRole, SnapshotStatus, SnapshotType
from codeatlas.domain.identity import chunk_version_id, logical_chunk_id
from codeatlas.repositories.snapshot_manager import SnapshotManager
from codeatlas.storage.sqlite.database import Database
from codeatlas.storage.sqlite.models import ChunkVersionModel, SnapshotModel
from codeatlas.storage.sqlite.repositories import ChunkStore, RepositoryStore, SnapshotStore

_PARSER = "0.1.0"
_CHUNKER = "0.1.0"


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


def _make_chunk(
    repo_id: str, path: str, name: str, content_hash: str
) -> tuple[LogicalChunk, ChunkVersion]:
    lc_id = logical_chunk_id(repo_id, path, name, ChunkRole.SYMBOL_IMPLEMENTATION)
    logical = LogicalChunk(
        id=lc_id,
        repository_id=repo_id,
        normalized_path=path,
        chunk_role=ChunkRole.SYMBOL_IMPLEMENTATION,
        qualified_name=name,
    )
    version = ChunkVersion(
        id=chunk_version_id(lc_id, content_hash, _PARSER, _CHUNKER),
        logical_chunk_id=lc_id,
        content_hash=content_hash,
        parser_version=_PARSER,
        chunker_version=_CHUNKER,
        start_line=1,
        end_line=10,
    )
    return logical, version


async def _add_chunk_to_snapshot(
    db: Database, snapshot_id: str, logical: LogicalChunk, version: ChunkVersion
) -> None:
    async with db.writer.transaction() as session:
        store = ChunkStore(session)
        await store.upsert_logical(logical)
        await store.upsert_version(version)
        await store.add_membership(snapshot_id, version.id)


async def _active_ids(db: Database, repo_id: str) -> list[str]:
    async with db.writer.read_session() as session:
        versions = await ChunkStore(session).active_chunk_versions(repo_id)
    return sorted(v.id for v in versions)


# --- Pragmas ------------------------------------------------------------------


async def test_mandatory_pragmas_applied(database: Database) -> None:
    async with database.engine.connect() as conn:
        fk = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar()
        journal = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar()
    assert fk == 1
    assert str(journal).lower() == "wal"


# --- Staging isolation --------------------------------------------------------


async def test_staging_snapshot_never_in_active_scope(database: Database) -> None:
    repo = await _seed_repo(database)
    manager = SnapshotManager(database.writer)
    snap = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    logical, version = _make_chunk(repo.id, "a.py", "f", "hash1")
    await _add_chunk_to_snapshot(database, snap.id, logical, version)

    # Snapshot is still STAGING -> nothing visible in active scope.
    assert await _active_ids(database, repo.id) == []

    await manager.begin_validation(snap.id)
    await manager.activate(snap.id)

    assert await _active_ids(database, repo.id) == [version.id]


# --- Content reuse across snapshots -------------------------------------------


async def test_unchanged_content_reused_across_snapshots(database: Database) -> None:
    repo = await _seed_repo(database)
    manager = SnapshotManager(database.writer)

    logical, version_a = _make_chunk(repo.id, "a.py", "f", "hash_same")
    snap_a = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await _add_chunk_to_snapshot(database, snap_a.id, logical, version_a)
    await manager.begin_validation(snap_a.id)
    await manager.activate(snap_a.id)

    # Second snapshot, identical logical chunk + identical content.
    logical2, version_b = _make_chunk(repo.id, "a.py", "f", "hash_same")
    assert version_b.id == version_a.id  # content-addressed reuse
    snap_b = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await _add_chunk_to_snapshot(database, snap_b.id, logical2, version_b)
    await manager.begin_validation(snap_b.id)
    await manager.activate(snap_b.id)

    # Exactly one physical chunk_versions row (reused, not duplicated).
    async with database.writer.read_session() as session:
        count = await session.scalar(select(func.count()).select_from(ChunkVersionModel))
    assert count == 1

    # snap_b active; snap_a superseded.
    async with database.writer.read_session() as session:
        stores = SnapshotStore(session)
        active = await stores.get_active(repo.id)
        prior = await stores.get(snap_a.id)
    assert active is not None and active.id == snap_b.id
    assert prior is not None and prior.status is SnapshotStatus.SUPERSEDED
    assert await _active_ids(database, repo.id) == [version_a.id]


# --- Deletion -----------------------------------------------------------------


async def test_deleted_content_absent_from_active_membership(database: Database) -> None:
    repo = await _seed_repo(database)
    manager = SnapshotManager(database.writer)

    keep_logical, keep = _make_chunk(repo.id, "keep.py", "k", "hk")
    drop_logical, drop = _make_chunk(repo.id, "drop.py", "d", "hd")

    snap_a = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await _add_chunk_to_snapshot(database, snap_a.id, keep_logical, keep)
    await _add_chunk_to_snapshot(database, snap_a.id, drop_logical, drop)
    await manager.begin_validation(snap_a.id)
    await manager.activate(snap_a.id)
    assert await _active_ids(database, repo.id) == sorted([keep.id, drop.id])

    # Re-scan drops drop.py: new snapshot only contains keep.
    snap_b = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
    await _add_chunk_to_snapshot(database, snap_b.id, keep_logical, keep)
    await manager.begin_validation(snap_b.id)
    await manager.activate(snap_b.id)

    assert await _active_ids(database, repo.id) == [keep.id]


async def test_only_one_active_snapshot_after_activation(database: Database) -> None:
    repo = await _seed_repo(database)
    manager = SnapshotManager(database.writer)
    for _ in range(3):
        snap = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)
        await manager.begin_validation(snap.id)
        await manager.activate(snap.id)

    async with database.writer.read_session() as session:
        active_count = await session.scalar(
            select(func.count())
            .select_from(SnapshotModel)
            .where(SnapshotModel.status == SnapshotStatus.ACTIVE.value)
        )
    assert active_count == 1
