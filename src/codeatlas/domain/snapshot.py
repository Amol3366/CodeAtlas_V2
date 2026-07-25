"""Snapshot identity and lifecycle state.

The lifecycle is an explicit enum rather than a boolean because partial and
failed work must be representable: a snapshot that failed while parsing is not
the same as one that was never built, and neither may be mistaken for the active
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SnapshotState(StrEnum):
    """Where a snapshot sits in the indexing lifecycle.

    ``ACTIVE`` is the only state visible to queries. Exactly one snapshot per
    repository may hold it, enforced by a partial unique index in SQLite.
    """

    DISCOVERED = "discovered"
    SCANNING = "scanning"
    PARSING = "parsing"
    INDEXING = "indexing"
    VALIDATING = "validating"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Snapshot:
    """One deterministic view of a repository at a point in time."""

    snapshot_id: str
    repository_id: str
    state: SnapshotState
    git_head: str | None
    git_branch: str | None
    git_dirty: bool
    working_tree_fingerprint: str
    file_count: int
    parsed_file_count: int
    skipped_file_count: int
    parse_error_count: int
    parser_bundle_version: str
    index_version: str
    created_at: datetime
    activated_at: datetime | None
