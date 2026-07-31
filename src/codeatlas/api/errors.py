"""Translation from application errors to the contract error envelope.

The mapping lives here so that no route invents its own status code or message
shape. Internal failures are deliberately opaque: the client gets a stable code
and a generic sentence, never an exception message, a stack trace, or a local
filesystem path.
"""

from __future__ import annotations

import uuid

from fastapi import Request, status
from fastapi.responses import JSONResponse

from codeatlas.contracts import ErrorDetail, ErrorEnvelope
from codeatlas.domain.errors import CodeAtlasError, ErrorCode

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: status.HTTP_400_BAD_REQUEST,
    ErrorCode.PATH_NOT_ALLOWED: status.HTTP_400_BAD_REQUEST,
    ErrorCode.PATH_OUTSIDE_ROOT: status.HTTP_400_BAD_REQUEST,
    ErrorCode.SCAN_LIMIT_EXCEEDED: status.HTTP_400_BAD_REQUEST,
    ErrorCode.UNSUPPORTED_QUERY_MODE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.SEARCH_QUERY_INVALID: status.HTTP_400_BAD_REQUEST,
    ErrorCode.REPOSITORY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.EVIDENCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.FILE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.SYMBOL_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.CHANGE_ANALYSIS_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.EMBEDDING_MIGRATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.GIT_REF_UNRESOLVABLE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.ANALYSIS_RULES_INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.REPOSITORY_ALREADY_REGISTERED: status.HTTP_409_CONFLICT,
    ErrorCode.SNAPSHOT_NOT_READY: status.HTTP_409_CONFLICT,
    ErrorCode.INDEX_IN_PROGRESS: status.HTTP_409_CONFLICT,
    ErrorCode.NO_ROLLBACK_TARGET: status.HTTP_409_CONFLICT,
    ErrorCode.CHANGE_ANALYSIS_REQUIRES_GIT: status.HTTP_409_CONFLICT,
    ErrorCode.CONVERSATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.MESSAGE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.RUN_NOT_CANCELLABLE: status.HTTP_409_CONFLICT,
    ErrorCode.RUN_NOT_RETRYABLE: status.HTTP_409_CONFLICT,
    ErrorCode.CONVERSATION_ARCHIVED: status.HTTP_409_CONFLICT,
    ErrorCode.QUERY_TOO_LONG: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.REPOSITORY_HAS_CONVERSATIONS: status.HTTP_409_CONFLICT,
    ErrorCode.WATCHER_UNAVAILABLE: status.HTTP_409_CONFLICT,
    ErrorCode.BACKUP_FAILED: status.HTTP_409_CONFLICT,
    ErrorCode.RESTORE_INCOMPATIBLE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.INTEGRITY_CHECK_FAILED: status.HTTP_409_CONFLICT,
    # Conflict rather than a server error: the request is well formed and the
    # service is running; it is the database on disk that this build cannot
    # serve, and no retry or rewording changes that.
    ErrorCode.SCHEMA_VERSION_UNSUPPORTED: status.HTTP_409_CONFLICT,
    ErrorCode.PROVIDER_DISABLED: status.HTTP_400_BAD_REQUEST,
    ErrorCode.PROVIDER_UNAVAILABLE: status.HTTP_409_CONFLICT,
    ErrorCode.PROVIDER_BUDGET_EXCEEDED: status.HTTP_409_CONFLICT,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def request_id_for(request: Request) -> str:
    """Use the caller's correlation ID when supplied, otherwise mint one."""
    supplied = request.headers.get("X-Request-Id")
    if supplied and supplied.strip():
        return supplied.strip()[:256]
    return f"req_{uuid.uuid4().hex}"


def error_response(
    request: Request,
    *,
    code: ErrorCode,
    message: str,
    retryable: bool,
    details: dict[str, str] | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    """Serialize one error using the contract envelope."""
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code.value,
            message=message,
            request_id=request_id_for(request),
            retryable=retryable,
            details=details or {},
        )
    )
    resolved = status_code or _STATUS_BY_CODE.get(
        code, status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    return JSONResponse(status_code=resolved, content=envelope.model_dump(mode="json"))


def codeatlas_error_response(request: Request, error: CodeAtlasError) -> JSONResponse:
    """Map a raised application error onto its HTTP response."""
    return error_response(
        request,
        code=error.code,
        message=error.message,
        retryable=error.retryable,
        details=error.details,
    )
