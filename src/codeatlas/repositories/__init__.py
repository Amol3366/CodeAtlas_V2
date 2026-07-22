"""Repository ingestion: scanning, path safety, ignore rules, Git state (Phase 1)."""

from __future__ import annotations

from codeatlas.repositories.git_service import GitChange, GitService, GitState
from codeatlas.repositories.scanner import (
    ManifestDiff,
    ManifestEntry,
    RepositoryScanner,
    ScanManifest,
    ScanResult,
    SkippedFile,
    SkipReason,
    diff_manifests,
)
from codeatlas.repositories.service import RepositoryService, repository_id_for

__all__ = [
    "GitChange",
    "GitService",
    "GitState",
    "ManifestDiff",
    "ManifestEntry",
    "RepositoryScanner",
    "RepositoryService",
    "ScanManifest",
    "ScanResult",
    "SkipReason",
    "SkippedFile",
    "diff_manifests",
    "repository_id_for",
]
