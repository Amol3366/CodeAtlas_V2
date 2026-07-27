"""Phase 5 adds the six conversation error codes and maps them to HTTP and CLI
exit codes the same way every existing code is mapped (ADR-0006 decision 10)."""

from __future__ import annotations

from fastapi import status

from codeatlas.api.errors import _STATUS_BY_CODE
from codeatlas.cli.main import _EXIT_BY_CODE
from codeatlas.domain.errors import (
    CodeAtlasError,
    ConversationArchivedError,
    ConversationNotFoundError,
    ErrorCode,
    MessageNotFoundError,
    QueryTooLongError,
    RunNotCancellableError,
    RunNotRetryableError,
)


def test_error_codes_are_part_of_the_public_contract() -> None:
    # A code missing from the enum would silently fall through to 500/6 in both
    # adapters, which is the failure mode this test exists to prevent.
    assert ErrorCode.CONVERSATION_NOT_FOUND == "CONVERSATION_NOT_FOUND"
    assert ErrorCode.MESSAGE_NOT_FOUND == "MESSAGE_NOT_FOUND"
    assert ErrorCode.RUN_NOT_CANCELLABLE == "RUN_NOT_CANCELLABLE"
    assert ErrorCode.RUN_NOT_RETRYABLE == "RUN_NOT_RETRYABLE"
    assert ErrorCode.CONVERSATION_ARCHIVED == "CONVERSATION_ARCHIVED"
    assert ErrorCode.QUERY_TOO_LONG == "QUERY_TOO_LONG"


def test_each_new_error_class_maps_to_its_documented_status_and_exit_code() -> None:
    # ADR-0006 documents these mappings; the adapters read them from the tables
    # here, so a missing entry is a contract break both tests catch directly.
    cases = [
        (ConversationNotFoundError, status.HTTP_404_NOT_FOUND, 3),
        (MessageNotFoundError, status.HTTP_404_NOT_FOUND, 3),
        (RunNotCancellableError, status.HTTP_409_CONFLICT, 3),
        (RunNotRetryableError, status.HTTP_409_CONFLICT, 3),
        (ConversationArchivedError, status.HTTP_409_CONFLICT, 3),
        (QueryTooLongError, status.HTTP_422_UNPROCESSABLE_CONTENT, 2),
    ]
    for error_class, http_status, cli_exit in cases:
        assert _STATUS_BY_CODE[error_class.code] == http_status
        assert _EXIT_BY_CODE[error_class.code] == cli_exit


def test_new_errors_inherit_the_safe_message_contract() -> None:
    error = ConversationNotFoundError("No conversation matches that ID.")
    assert isinstance(error, CodeAtlasError)
    assert error.code is ErrorCode.CONVERSATION_NOT_FOUND
    assert error.retryable is False
    # A run that is not cancellable *now* may be later (it may still be
    # queued); the flag says "ask again", and ADR-0006 leaves every other
    # class at the non-retryable default.
    assert RunNotCancellableError("x").retryable is True
