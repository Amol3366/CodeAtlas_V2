"""Phase 6 adds the four hardening error codes (ADR-0007).

Each names a failure a user will actually hit while running CodeAtlas rather
than while developing it: a watcher that could not start, a backup that did not
finish, a restore from an incompatible database, and a database that failed its
integrity check.
"""

from __future__ import annotations

from fastapi import status

from codeatlas.api.errors import _STATUS_BY_CODE
from codeatlas.cli.main import _EXIT_BY_CODE
from codeatlas.domain.errors import (
    BackupFailedError,
    CodeAtlasError,
    ErrorCode,
    IntegrityCheckFailedError,
    RestoreIncompatibleError,
    WatcherUnavailableError,
)


def test_error_codes_are_part_of_the_public_contract() -> None:
    assert ErrorCode.WATCHER_UNAVAILABLE == "WATCHER_UNAVAILABLE"
    assert ErrorCode.BACKUP_FAILED == "BACKUP_FAILED"
    assert ErrorCode.RESTORE_INCOMPATIBLE == "RESTORE_INCOMPATIBLE"
    assert ErrorCode.INTEGRITY_CHECK_FAILED == "INTEGRITY_CHECK_FAILED"


def test_each_new_error_class_maps_to_its_documented_status_and_exit_code() -> None:
    cases = [
        (WatcherUnavailableError, status.HTTP_409_CONFLICT, 3),
        (BackupFailedError, status.HTTP_409_CONFLICT, 6),
        (RestoreIncompatibleError, status.HTTP_422_UNPROCESSABLE_CONTENT, 2),
        (IntegrityCheckFailedError, status.HTTP_409_CONFLICT, 3),
    ]
    for error_class, http_status, cli_exit in cases:
        assert _STATUS_BY_CODE[error_class.code] == http_status
        assert _EXIT_BY_CODE[error_class.code] == cli_exit


def test_the_transient_failures_are_the_retryable_ones() -> None:
    """A watcher that could not start and a backup that was blocked may both
    succeed on the next attempt; an incompatible database and a failed
    integrity check will not, and telling a user to retry those would send them
    in a circle."""
    assert WatcherUnavailableError("x").retryable is True
    assert BackupFailedError("x").retryable is True
    assert RestoreIncompatibleError("x").retryable is False
    assert IntegrityCheckFailedError("x").retryable is False


def test_new_errors_inherit_the_safe_message_contract() -> None:
    error = RestoreIncompatibleError("That backup was written by a newer build.")
    assert isinstance(error, CodeAtlasError)
    assert error.code is ErrorCode.RESTORE_INCOMPATIBLE
