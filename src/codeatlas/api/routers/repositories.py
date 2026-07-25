"""Repository registration, indexing, status, and diagnostics routes.

These models are the HTTP projection of the application dataclasses. They never
redefine a contract type: `SnapshotReference` and everything under it come
straight from `codeatlas.contracts`.

The absolute repository root is deliberately not returned. A local client already
knows the path it registered, and echoing it back widens what a diagnostic bundle
or a screenshot can leak.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.application.container import ApplicationServices
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import SnapshotReference
from codeatlas.domain.errors import SnapshotNotReadyError
from codeatlas.domain.repository import Repository, ScanLimits

router = APIRouter(prefix="/v1/repositories", tags=["repositories"])


class StrictModel(BaseModel):
    """Reject unknown fields at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid")


class RegisterRepositoryBody(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    display_name: str | None = Field(default=None, max_length=256)


class RepositoryResponse(StrictModel):
    repository_id: str
    display_name: str
    created_at: str


class IndexResponse(StrictModel):
    job_id: str
    snapshot_id: str
    state: str
    file_count: int
    parsed_file_count: int
    skipped_file_count: int
    parse_error_count: int
    warnings: list[str]


class LimitsResponse(StrictModel):
    max_files: int
    max_file_bytes: int
    max_depth: int
    max_relative_path_length: int


class StatusResponse(StrictModel):
    repository_id: str
    snapshot: SnapshotReference | None
    file_count: int
    symbol_count: int
    parse_error_count: int
    warnings: list[str]


class DiagnosticsResponse(StrictModel):
    repository_id: str
    snapshot_id: str | None
    skipped_by_reason: dict[str, int]
    parse_error_count: int
    limits: LimitsResponse
    warnings: list[str]


def get_services(request: Request) -> ApplicationServices:
    """Provide per-request application services."""
    factory = request.app.state.services_factory
    services: ApplicationServices = factory()
    return services


Services = Annotated[ApplicationServices, Depends(get_services)]


@router.post("", status_code=status.HTTP_201_CREATED)
def register_repository(
    body: RegisterRepositoryBody, services: Services
) -> RepositoryResponse:
    repository = services.registration.register(
        RegisterRepositoryRequest(path=body.path, display_name=body.display_name)
    )
    return _repository_response(repository)


@router.get("")
def list_repositories(services: Services) -> list[RepositoryResponse]:
    return [_repository_response(item) for item in services.registration.list_all()]


@router.get("/{repository_id}")
def get_repository(repository_id: str, services: Services) -> RepositoryResponse:
    return _repository_response(services.registration.get(repository_id))


@router.post("/{repository_id}/index")
def index_repository(repository_id: str, services: Services) -> IndexResponse:
    result = services.indexing.index(repository_id)
    return IndexResponse(
        job_id=result.job_id,
        snapshot_id=result.snapshot.snapshot_id,
        state=result.snapshot.state.value,
        file_count=result.snapshot.file_count,
        parsed_file_count=result.snapshot.parsed_file_count,
        skipped_file_count=result.snapshot.skipped_file_count,
        parse_error_count=result.snapshot.parse_error_count,
        warnings=list(result.warnings),
    )


@router.get("/{repository_id}/status")
def repository_status(repository_id: str, services: Services) -> StatusResponse:
    status_result = services.status.status(repository_id)
    return StatusResponse(
        repository_id=repository_id,
        snapshot=status_result.snapshot,
        file_count=status_result.file_count,
        symbol_count=status_result.symbol_count,
        parse_error_count=status_result.parse_error_count,
        warnings=list(status_result.warnings),
    )


@router.get("/{repository_id}/diagnostics")
def repository_diagnostics(
    repository_id: str, services: Services
) -> DiagnosticsResponse:
    diagnostics = services.status.diagnostics(repository_id)
    return DiagnosticsResponse(
        repository_id=diagnostics.repository_id,
        snapshot_id=diagnostics.snapshot_id,
        skipped_by_reason=dict(diagnostics.skipped_by_reason),
        parse_error_count=diagnostics.parse_error_count,
        limits=_limits_response(diagnostics.limits),
        warnings=list(diagnostics.warnings),
    )


@router.get("/{repository_id}/snapshots/active")
def active_snapshot(
    repository_id: str, services: Services, response: Response
) -> SnapshotReference:
    services.registration.get(repository_id)
    status_result = services.status.status(repository_id)
    if status_result.snapshot is None:
        raise SnapshotNotReadyError(
            "The repository has no active snapshot. Index it first."
        )
    return status_result.snapshot


def _repository_response(repository: Repository) -> RepositoryResponse:
    return RepositoryResponse(
        repository_id=repository.repository_id,
        display_name=repository.display_name,
        created_at=repository.created_at.isoformat(),
    )


def _limits_response(limits: ScanLimits) -> LimitsResponse:
    return LimitsResponse(
        max_files=limits.max_files,
        max_file_bytes=limits.max_file_bytes,
        max_depth=limits.max_depth,
        max_relative_path_length=limits.max_relative_path_length,
    )
