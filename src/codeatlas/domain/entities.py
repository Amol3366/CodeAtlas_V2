"""Core domain entities (no I/O, no framework imports — CLAUDE.md §4).

Only the entities needed by the current phase live here. Snapshot/File/Symbol
and the rest of Blueprint §10 arrive with their phases. These are plain frozen
dataclasses; API schemas (Pydantic) and ORM models are mapped separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from codeatlas.domain.enums import (
    ChunkRole,
    FileClassification,
    IndexStatus,
    JobStatus,
    JobType,
    Language,
    ParseStatus,
    SnapshotStatus,
    SnapshotType,
)


@dataclass(frozen=True)
class Repository:
    """A registered local repository (Blueprint §4.3.1 / §10.1).

    ``root_path`` preserves the original casing for display; ``normalized_root_path``
    is the case/slash-normalized comparison key (CLAUDE.md §2.13). ``id`` is
    derived deterministically from the normalized root so re-registering the same
    directory is idempotent (CLAUDE.md §2.9).
    """

    id: str
    name: str
    root_path: str
    normalized_root_path: str
    is_git_repository: bool
    default_branch: str | None = None
    created_at: datetime | None = None
    last_indexed_at: datetime | None = None


@dataclass(frozen=True)
class Snapshot:
    """A versioned repository snapshot (Blueprint §10.2 / §4.3.6-4.3.7).

    Freshness is dual-tracked: ``deterministic_index_status`` becomes ``READY``
    immediately after a successful parse, while ``semantic_index_status`` may lag
    and must be *visibly* partial (CLAUDE.md §5). A snapshot is only queryable in
    active scope once ``status == ACTIVE``.
    """

    id: str
    repository_id: str
    snapshot_type: SnapshotType
    status: SnapshotStatus
    parser_bundle_version: str
    chunker_version: str
    retrieval_policy_version: str
    deterministic_index_status: IndexStatus = IndexStatus.PENDING
    semantic_index_status: IndexStatus = IndexStatus.PENDING
    branch: str | None = None
    commit_sha: str | None = None
    working_tree_hash: str | None = None
    semantic_coverage: float = 0.0
    pending_embedding_count: int = 0
    active_embedding_namespace: str | None = None
    created_at: datetime | None = None
    activated_at: datetime | None = None


@dataclass(frozen=True)
class FileRecord:
    """A file belonging to a snapshot (Blueprint §10.3)."""

    id: str
    snapshot_id: str
    relative_path: str
    normalized_path: str
    content_hash: str
    classification: FileClassification
    language: Language | None = None
    size_bytes: int = 0
    line_count: int = 0
    generated: bool = False
    binary: bool = False
    parse_status: ParseStatus = ParseStatus.PENDING


@dataclass(frozen=True)
class LogicalChunk:
    """The stable logical slot of a chunk (Blueprint §10.10). ``id`` is content-independent."""

    id: str
    repository_id: str
    normalized_path: str
    chunk_role: ChunkRole
    qualified_name: str | None = None


@dataclass(frozen=True)
class ChunkVersion:
    """A specific content version of a logical chunk (Blueprint §10.11).

    Reused verbatim across snapshots/branches when content is unchanged: the
    ``id`` (``chunk_version_id``) is identical, so the row is inserted once.
    """

    id: str
    logical_chunk_id: str
    content_hash: str
    parser_version: str
    chunker_version: str
    start_line: int
    end_line: int
    raw_content: str = ""
    retrieval_content: str = ""


@dataclass(frozen=True)
class IndexJob:
    """A resumable indexing job (Blueprint §4.10). ``cursor`` supports resumption."""

    id: str
    repository_id: str
    job_type: JobType
    status: JobStatus
    snapshot_id: str | None = None
    attempts: int = 0
    error: str | None = None
    cursor: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
