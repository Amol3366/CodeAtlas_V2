"""Typed domain exceptions.

Adapters (HTTP/CLI/MCP) translate these into their own stable error contracts
(CLAUDE.md §13). Domain code raises these rather than framework exceptions so the
core stays framework-free.
"""

from __future__ import annotations


class CodeAtlasError(Exception):
    """Base class for all CodeAtlas domain errors."""


class RepositoryError(CodeAtlasError):
    """Repository registration / resolution failures."""


class PathSecurityError(RepositoryError):
    """A path escaped the repository root, followed an external junction, or was disallowed."""


class UnsupportedPathError(RepositoryError):
    """A UNC or otherwise disallowed path was supplied without explicit opt-in."""


class SnapshotError(CodeAtlasError):
    """Snapshot lifecycle / consistency violations."""


class SnapshotConsistencyError(SnapshotError):
    """Evidence from a non-active snapshot leaked into an active-scope result."""


class ParseError(CodeAtlasError):
    """A parser failed irrecoverably (diagnostics are preferred over raising)."""


class StorageError(CodeAtlasError):
    """SQLite / vector-store failures."""


class StoreConsistencyError(StorageError):
    """SQLite and the vector store disagree about membership."""


class ProviderError(CodeAtlasError):
    """An optional embedding/answer provider failed or was misconfigured."""


class BudgetExhaustedError(ProviderError):
    """A configured token/request budget was exhausted; fall back to deterministic output."""


class EvidenceValidationError(CodeAtlasError):
    """A citation or claim failed validation and must not be displayed."""
