"""Phase 4 adds the four change-assurance error codes and maps them to HTTP and
CLI exit codes the same way every existing code is mapped."""

from __future__ import annotations

from fastapi import status

from codeatlas.api.errors import _STATUS_BY_CODE
from codeatlas.cli.main import _EXIT_BY_CODE
from codeatlas.domain.errors import (
    AnalysisRulesInvalidError,
    ChangeAnalysisNotFoundError,
    ChangeAnalysisRequiresGitError,
    CodeAtlasError,
    ErrorCode,
    GitRefUnresolvableError,
)


def test_error_codes_are_part_of_the_public_contract() -> None:
    # A code missing from the enum would silently fall through to 500/6 in both
    # adapters, which is the failure mode this test exists to prevent.
    assert ErrorCode.CHANGE_ANALYSIS_REQUIRES_GIT == "CHANGE_ANALYSIS_REQUIRES_GIT"
    assert ErrorCode.GIT_REF_UNRESOLVABLE == "GIT_REF_UNRESOLVABLE"
    assert ErrorCode.CHANGE_ANALYSIS_NOT_FOUND == "CHANGE_ANALYSIS_NOT_FOUND"
    assert ErrorCode.ANALYSIS_RULES_INVALID == "ANALYSIS_RULES_INVALID"


def test_each_new_error_class_maps_to_its_documented_status_and_exit_code() -> None:
    # ADR-0005 documents these mappings; the adapters read them from the tables
    # here, so a missing entry is a contract break both tests catch directly.
    cases = [
        (ChangeAnalysisRequiresGitError, status.HTTP_409_CONFLICT, 3),
        (GitRefUnresolvableError, status.HTTP_400_BAD_REQUEST, 2),
        (ChangeAnalysisNotFoundError, status.HTTP_404_NOT_FOUND, 3),
        (AnalysisRulesInvalidError, status.HTTP_422_UNPROCESSABLE_CONTENT, 2),
    ]
    for error_class, http_status, cli_exit in cases:
        assert _STATUS_BY_CODE[error_class.code] == http_status
        assert _EXIT_BY_CODE[error_class.code] == cli_exit


def test_new_errors_inherit_the_safe_message_contract() -> None:
    error = GitRefUnresolvableError("HEAD~42 could not be resolved.")
    assert isinstance(error, CodeAtlasError)
    assert error.code is ErrorCode.GIT_REF_UNRESOLVABLE
    assert error.retryable is False
    # The retryable flag is the only one ADR-0005 leaves non-default.
    assert ChangeAnalysisRequiresGitError("x").retryable is True