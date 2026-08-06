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
    REPOSITORY_HAS_CONVERSATIONS = "REPOSITORY_HAS_CONVERSATIONS"
    WATCHER_UNAVAILABLE = "WATCHER_UNAVAILABLE"
    BACKUP_FAILED = "BACKUP_FAILED"
    RESTORE_INCOMPATIBLE = "RESTORE_INCOMPATIBLE"
    INTEGRITY_CHECK_FAILED = "INTEGRITY_CHECK_FAILED"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_BUDGET_EXCEEDED = "PROVIDER_BUDGET_EXCEEDED"
    CREDENTIAL_STORE_UNAVAILABLE = "CREDENTIAL_STORE_UNAVAILABLE"
    CREDENTIAL_WRITE_FAILED = "CREDENTIAL_WRITE_FAILED"
    EMBEDDING_MIGRATION_NOT_FOUND = "EMBEDDING_MIGRATION_NOT_FOUND"
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


class RepositoryHasConversationsError(CodeAtlasError):
    """Deleting the repository would take its conversations with it.

    Added in P6-05, beyond the four codes ADR-0007 declared, because the schema
    cascades `conversations` from `repositories`: without an explicit refusal a
    user freeing index space would silently lose chat history and find out only
    by going to look for it.

    Not retryable — retrying deletes nothing extra. The caller must decide to
    cascade, which is a choice rather than a repeat.
    """

    code = ErrorCode.REPOSITORY_HAS_CONVERSATIONS
    retryable = False


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


class SchemaVersionUnsupportedError(CodeAtlasError):
    """The database was written by a newer build than the one running.

    Migrations are forward-only, so there is no honest way to read a schema this
    build has never seen. Continuing anyway is the dangerous option: the tables
    would open, the queries would mostly work, and writes would land in columns
    whose meaning had changed — silent corruption, discovered later.

    Not retryable. The remedy is to run the newer build, or to restore a backup
    taken before the upgrade, and neither happens by trying again.
    """

    code = ErrorCode.SCHEMA_VERSION_UNSUPPORTED


class IntegrityCheckFailedError(CodeAtlasError):
    """The database failed its integrity check.

    Not retryable: a corrupted file does not repair itself. The operation stops
    rather than reading from it, because answering from a corrupted index would
    produce evidence that cannot be trusted and would not announce itself.
    """

    code = ErrorCode.INTEGRITY_CHECK_FAILED


class ProviderDisabledError(CodeAtlasError):
    """A model provider was asked to work while switched off.

    Reaching this is not a user-facing failure in normal operation: the
    deterministic path never calls a provider, so the caller falls back and
    answers without one. It exists so that a wiring mistake fails loudly
    instead of a disabled provider returning zero vectors, which would rank
    every candidate equally and look like a working search.

    Not retryable. Nothing to retry — someone chose this setting.
    """

    code = ErrorCode.PROVIDER_DISABLED


class ProviderUnavailableError(CodeAtlasError):
    """A provider is selected but cannot run here.

    The common cause is the one a user actually hits: the setting was switched
    on before the optional extra was installed. The message names the extra,
    because an ``ImportError`` surfacing from three frames down does not tell
    anyone what to do next.

    Retryable: installing the package, restoring the network, or restoring the
    credential fixes it without changing any setting.
    """

    code = ErrorCode.PROVIDER_UNAVAILABLE
    retryable = True


class ProviderBudgetExceededError(CodeAtlasError):
    """A provider call would spend more than the repository allows.

    Raised *before* the request is sent, which is the only point where the
    refusal is worth anything: a budget checked afterwards has already been
    exceeded.

    Not retryable, and deliberately so. Section 10.3 reserves retries for
    transient failures; this is a standing decision the user made about
    spending, and retrying it would burn the allowance on an answer that
    cannot change until someone raises the budget. Callers degrade to the
    deterministic result instead.
    """

    code = ErrorCode.PROVIDER_BUDGET_EXCEEDED


class EmbeddingMigrationNotFoundError(CodeAtlasError):
    """No shadow embedding migration matches the supplied ID."""

    code = ErrorCode.EMBEDDING_MIGRATION_NOT_FOUND


class CredentialStoreUnavailableError(CodeAtlasError):
    """No OS credential store on this platform.

    Not an internal error: on a non-Windows machine this is the expected
    state, and `.env` remains a supported way to supply the key.
    """

    code = ErrorCode.CREDENTIAL_STORE_UNAVAILABLE


class CredentialWriteFailedError(CodeAtlasError):
    """The OS credential store rejected the write.

    The underlying Windows error number goes in `details`, never the value
    that was being written.
    """

    code = ErrorCode.CREDENTIAL_WRITE_FAILED

