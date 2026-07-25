"""Repository, scan limit, and file-record domain types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FileClassification(StrEnum):
    """How a file participates in repository truth and impact analysis."""

    SOURCE_CODE = "source_code"
    TEST_CODE = "test_code"
    DOCUMENTATION = "documentation"
    ARCHITECTURE_DECISION = "architecture_decision"
    API_SPECIFICATION = "api_specification"
    CONFIGURATION = "configuration"
    DATABASE_SCHEMA = "database_schema"
    MIGRATION = "migration"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    LOCKFILE = "lockfile"
    INFRASTRUCTURE = "infrastructure"
    GENERATED = "generated"
    VENDOR = "vendor"
    BINARY = "binary"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScanLimits:
    """Bounds that keep a scan terminating and bounded on hostile input."""

    max_files: int = 50_000
    max_file_bytes: int = 2_000_000
    max_depth: int = 40
    max_relative_path_length: int = 1024


@dataclass(frozen=True)
class FileRecord:
    """One file admitted into a snapshot."""

    file_id: str
    relative_path: str
    display_path: str
    content_hash: str
    size_bytes: int
    line_count: int
    language: str
    classification: FileClassification


@dataclass(frozen=True)
class Repository:
    """A registered local repository root."""

    repository_id: str
    display_name: str
    canonical_root: str
    created_at: datetime
