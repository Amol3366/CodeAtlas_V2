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
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    RUN_NOT_CANCELLABLE = "RUN_NOT_CANCELLABLE"
    RUN_NOT_RETRYABLE = "RUN_NOT_RETRYABLE"
    CONVERSATION_ARCHIVED = "CONVERSATION_ARCHIVED"
    QUERY_TOO_LONG = "QUERY_TOO_LONG"
    WATCHER_UNAVAILABLE = "WATCHER_UNAVAILABLE"
    BACKUP_FAILED = "BACKUP_FAILED"
    RESTORE_INCOMPATIBLE = "RESTORE_INCOMPATIBLE"
    INTEGRITY_CHECK_FAILED = "INTEGRITY_CHECK_FAILED"
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


class ConversationNotFoundError(CodeAtlasError):
    """No conversation matches the supplied ID.

    A soft-deleted conversation is *not found* to every caller that did not ask
    for deleted rows: deletion is a user-visible fact, and reporting the row
    because it physically survives would contradict what the user was told.
    """

    code = ErrorCode.CONVERSATION_NOT_FOUND


class MessageNotFoundError(CodeAtlasError):
    """No message matches the supplied ID within its conversation."""

    code = ErrorCode.MESSAGE_NOT_FOUND


class RunNotCancellableError(CodeAtlasError):
    """The run has already reached a terminal state.

    Retryable because the answer depends on when the question is asked: a run
    that finished between the client's decision and its request was cancellable
    a moment earlier, and the client's next poll sees the terminal state.
    """

    code = ErrorCode.RUN_NOT_CANCELLABLE
    retryable = True


class RunNotRetryableError(CodeAtlasError):
    """The message has no failed or cancelled run to retry.

    Retrying a running or completed message would create a second answer for
    one question, which the persisted-answer contract does not allow.
    """

    code = ErrorCode.RUN_NOT_RETRYABLE


class ConversationArchivedError(CodeAtlasError):
    """The conversation is archived and accepts no new messages.

    Archiving is the user's statement that a thread is finished. Silently
    reopening it on a new message would discard that statement.
    """

    code = ErrorCode.CONVERSATION_ARCHIVED


class QueryTooLongError(CodeAtlasError):
    """The submitted question exceeds the maximum query length.

    Every request carries a bounded input size (`AGENTS.md` Section 10.3);
    truncating instead would answer a question the user did not ask.
    """

    code = ErrorCode.QUERY_TOO_LONG


class WatcherUnavailableError(CodeAtlasError):
    """The filesystem watcher could not start or could not keep watching.

    Retryable because the usual causes — exhausted handles, a directory that
    momentarily vanished — clear on their own. Indexing is unaffected: the
    watcher is a trigger, never an authority, so its absence costs freshness
    rather than correctness.
    """

    code = ErrorCode.WATCHER_UNAVAILABLE
    retryable = True


class BackupFailedError(CodeAtlasError):
    """A backup did not complete, so no backup was produced.

    Retryable: a busy database is the common cause. A partial file is never
    left behind — a backup a user believes in but cannot restore from is worse
    than no backup at all.
    """

    code = ErrorCode.BACKUP_FAILED
    retryable = True


class RestoreIncompatibleError(CodeAtlasError):
    """The backup cannot be restored into this build.

    A database written by a newer schema version cannot be migrated backwards.
    Refusing is the only safe answer; retrying would fail identically, so this
    is not retryable.
    """

    code = ErrorCode.RESTORE_INCOMPATIBLE


class IntegrityCheckFailedError(CodeAtlasError):
    """The database failed its integrity check.

    Not retryable: a corrupted file does not repair itself. The operation stops
    rather than reading from it, because answering from a corrupted index would
    produce evidence that cannot be trusted and would not announce itself.
    """

    code = ErrorCode.INTEGRITY_CHECK_FAILED
