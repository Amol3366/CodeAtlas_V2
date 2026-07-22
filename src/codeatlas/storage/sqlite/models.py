"""SQLAlchemy 2.0 ORM models — SQLite is the single source of truth (CLAUDE.md §3).

Tables mirror Blueprint §10 / §4.7.1. Embedding and migration tables exist even
while embeddings are disabled (Phase 2 build item), so the schema never changes
when semantic features are switched on. Enum-valued columns are stored as their
string values; the data-access layer maps to/from the domain enums.

These ORM models are deliberately separate from the domain dataclasses
(`domain/entities.py`) and the API/wire contracts (`contracts.py`) — mapping is
explicit (CLAUDE.md §13).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all CodeAtlas ORM models."""


class RepositoryModel(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    root_path: Mapped[str] = mapped_column(String, nullable=False)
    normalized_root_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    is_git_repository: Mapped[bool] = mapped_column(Boolean, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapshotModel(Base):
    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshots_repo_status", "repository_id", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    deterministic_index_status: Mapped[str] = mapped_column(String, nullable=False)
    semantic_index_status: Mapped[str] = mapped_column(String, nullable=False)
    semantic_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pending_embedding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_embedding_namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    working_tree_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_bundle_version: Mapped[str] = mapped_column(String, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String, nullable=False)
    retrieval_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FileModel(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "normalized_path", name="uq_files_snapshot_path"),
        Index("ix_files_snapshot", "snapshot_id"),
        Index("ix_files_content_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    normalized_path: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    classification: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    binary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parse_status: Mapped[str] = mapped_column(String, nullable=False)


class LogicalChunkModel(Base):
    __tablename__ = "logical_chunks"
    __table_args__ = (Index("ix_logical_chunks_repo_path", "repository_id", "normalized_path"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    normalized_path: Mapped[str] = mapped_column(String, nullable=False)
    qualified_name: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_role: Mapped[str] = mapped_column(String, nullable=False)


class ChunkVersionModel(Base):
    __tablename__ = "chunk_versions"
    __table_args__ = (Index("ix_chunk_versions_logical", "logical_chunk_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    logical_chunk_id: Mapped[str] = mapped_column(
        ForeignKey("logical_chunks.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    parser_version: Mapped[str] = mapped_column(String, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retrieval_content: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SnapshotChunkMembershipModel(Base):
    __tablename__ = "snapshot_chunk_membership"
    __table_args__ = (Index("ix_membership_chunk_version", "chunk_version_id"),)

    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_version_id: Mapped[str] = mapped_column(
        ForeignKey("chunk_versions.id", ondelete="CASCADE"), primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EmbeddingRecordModel(Base):
    __tablename__ = "embedding_records"
    __table_args__ = (Index("ix_embedding_records_content", "content_hash"),)

    embedding_key: Mapped[str] = mapped_column(String, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    normalization_version: Mapped[str] = mapped_column(String, nullable=False)
    namespace: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelMigrationModel(Base):
    __tablename__ = "model_migrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )
    source_namespace: Mapped[str] = mapped_column(String, nullable=False)
    target_namespace: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    active_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedded_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evaluation_status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ParseDiagnosticModel(Base):
    __tablename__ = "parse_diagnostics"
    __table_args__ = (Index("ix_parse_diagnostics_snapshot", "snapshot_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=True
    )
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IndexJobModel(Base):
    __tablename__ = "index_jobs"
    __table_args__ = (Index("ix_index_jobs_status", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
