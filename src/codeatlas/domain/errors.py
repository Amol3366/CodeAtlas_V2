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
    SEARCH_QUERY_INVALID = "SEARCH_QUERY_INVALID"
    NO_ROLLBACK_TARGET = "NO_ROLLBACK_TARGET"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    CHANGE_ANALYSIS_REQUIRES_GIT = "CHANGE_ANALYSIS_REQUIRES_GIT"
    GIT_REF_UNRESOLVABLE = "GIT_REF_UNRESOLVABLE"
    CHANGE_ANALYSIS_NOT_FOUND = "CHANGE_ANALYSIS_NOT_FOUND"
    ANALYSIS_RULES_INVALID = "ANALYSIS_RULES_INVALID"
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


class SearchQueryError(CodeAtlasError):
    """The search query is empty, too long, or unusable after sanitization."""

    code = ErrorCode.SEARCH_QUERY_INVALID


class NoRollbackTargetError(CodeAtlasError):
    """No superseded snapshot exists to roll back to."""

    code = ErrorCode.NO_ROLLBACK_TARGET


class EvidenceNotFoundError(CodeAtlasError):
    """No such evidence in the active snapshot.

    Evidence IDs are content-derived, so an unknown one means either a typo or a
    citation from a snapshot that is no longer active. Both are the caller's to
    resolve; neither is answered by guessing a nearby range.
    """

    code = ErrorCode.EVIDENCE_NOT_FOUND


class FileNotFoundInSnapshotError(CodeAtlasError):
    """No such file in the active snapshot."""

    code = ErrorCode.FILE_NOT_FOUND


class SymbolNotFoundError(CodeAtlasError):
    """No such symbol in the active snapshot."""

    code = ErrorCode.SYMBOL_NOT_FOUND


class ChangeAnalysisRequiresGitError(CodeAtlasError):
    """A working-tree or commit-range analysis needs a Git base to diff against.

    A non-Git directory has no recorded pre-change state, so the analysis cannot
    identify what changed. The caller is told exactly that, rather than given a
    guess assembled from whatever happens to be on disk.
    """

    code = ErrorCode.CHANGE_ANALYSIS_REQUIRES_GIT
    retryable = True


class GitRefUnresolvableError(CodeAtlasError):
    """A supplied ref did not resolve to a Git commit."""

    code = ErrorCode.GIT_REF_UNRESOLVABLE


class ChangeAnalysisNotFoundError(CodeAtlasError):
    """No persisted analysis matches the supplied ID."""

    code = ErrorCode.CHANGE_ANALYSIS_NOT_FOUND


class AnalysisRulesInvalidError(CodeAtlasError):
    """A repository rules file failed strict validation.

    Rules are untrusted repository content: an unknown field, a bad glob, or an
    invalid severity is refused rather than silently ignored. The analysis
    proceeds without rules rather than with a partial or hostile interpretation.
    """

    code = ErrorCode.ANALYSIS_RULES_INVALID
