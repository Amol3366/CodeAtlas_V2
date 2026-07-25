"""Stable error codes and the exception hierarchy shared by every adapter.

Adapters map :class:`CodeAtlasError` to their own transport: the REST layer to an
HTTP status plus the contract ``ErrorEnvelope``, the CLI to an exit code. Messages
are safe to show a user: they never contain absolute local paths, source
excerpts, secrets, or stack traces.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Machine-readable error codes. These are part of the public contract."""

    INVALID_REQUEST = "INVALID_REQUEST"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    PATH_OUTSIDE_ROOT = "PATH_OUTSIDE_ROOT"
    SCAN_LIMIT_EXCEEDED = "SCAN_LIMIT_EXCEEDED"
    REPOSITORY_NOT_FOUND = "REPOSITORY_NOT_FOUND"
    REPOSITORY_ALREADY_REGISTERED = "REPOSITORY_ALREADY_REGISTERED"
    SNAPSHOT_NOT_READY = "SNAPSHOT_NOT_READY"
    INDEX_IN_PROGRESS = "INDEX_IN_PROGRESS"
    UNSUPPORTED_QUERY_MODE = "UNSUPPORTED_QUERY_MODE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class CodeAtlasError(Exception):
    """Base class for every error that crosses an application boundary."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, str] = dict(details or {})


class InvalidRequestError(CodeAtlasError):
    code = ErrorCode.INVALID_REQUEST


class PathSafetyError(CodeAtlasError):
    """The supplied path is missing, unreadable, or not an allowed root."""

    code = ErrorCode.PATH_NOT_ALLOWED


class PathOutsideRootError(CodeAtlasError):
    """The resolved target escapes the approved repository root."""

    code = ErrorCode.PATH_OUTSIDE_ROOT


class ScanLimitExceededError(CodeAtlasError):
    code = ErrorCode.SCAN_LIMIT_EXCEEDED


class RepositoryNotFoundError(CodeAtlasError):
    code = ErrorCode.REPOSITORY_NOT_FOUND


class RepositoryAlreadyRegisteredError(CodeAtlasError):
    code = ErrorCode.REPOSITORY_ALREADY_REGISTERED


class SnapshotNotReadyError(CodeAtlasError):
    """No deterministic snapshot is active for the repository."""

    code = ErrorCode.SNAPSHOT_NOT_READY
    retryable = True


class IndexInProgressError(CodeAtlasError):
    code = ErrorCode.INDEX_IN_PROGRESS
    retryable = True


class UnsupportedQueryModeError(CodeAtlasError):
    code = ErrorCode.UNSUPPORTED_QUERY_MODE
