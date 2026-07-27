"""Repository registration, indexing, status, and diagnostics routes.

These models are the HTTP projection of the application dataclasses. They never
redefine a contract type: `SnapshotReference` and everything under it come
straight from `codeatlas.contracts`.

The absolute repository root is deliberately not returned. A local client already
knows the path it registered, and echoing it back widens what a diagnostic bundle
or a screenshot can leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.application.container import ApplicationServices
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.watching import WatchService
from codeatlas.contracts import SnapshotFreshness, SnapshotReference
from codeatlas.domain.errors import RepositoryNotFoundError, SnapshotNotReadyError
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


def get_services(request: Request) -> Iterator[ApplicationServices]:
    """Provide application services bound to this request's connection.

    A generator dependency, so the connection is closed when the request ends
    rather than living as long as the process. See `_services_factory` for why
    the lifetime has to be the request and not the application or the thread.
    """
    factory = request.app.state.services_factory
    with factory() as services:
        yield services


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


class FileEntry(StrictModel):
    file_id: str
    path: str
    language: str
    classification: str
    line_count: int
    size_bytes: int


class FilesResponse(StrictModel):
    repository_id: str
    snapshot: SnapshotReference
    files: list[FileEntry]


@router.get("/{repository_id}/files")
def repository_files(repository_id: str, services: Services) -> FilesResponse:
    """List the files the active snapshot contains.

    Paths are repository-relative, as everywhere else: the absolute root is not
    echoed back, so a screenshot or diagnostic bundle cannot leak it.
    """
    services.registration.get(repository_id)
    snapshot = services.indexing.get_active_snapshot(repository_id)
    if snapshot is None:
        raise SnapshotNotReadyError(
            "The repository has no active snapshot. Index it first."
        )
    return FilesResponse(
        repository_id=repository_id,
        snapshot=SnapshotReference(
            snapshot_id=snapshot.snapshot_id,
            git_head=snapshot.git_head,
            working_tree_fingerprint=snapshot.working_tree_fingerprint,
            freshness=SnapshotFreshness.FRESH,
            semantic_coverage=0.0,
        ),
        files=[
            FileEntry(
                file_id=record.file_id,
                path=record.relative_path,
                language=record.language,
                classification=record.classification.value,
                line_count=record.line_count,
                size_bytes=record.size_bytes,
            )
            for record in services.indexing.list_files(snapshot.snapshot_id)
        ],
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


@router.post("/{repository_id}/rollback")
def rollback(repository_id: str, services: Services) -> SnapshotReference:
    """Restore the previous snapshot as active.

    The escape hatch for an activation that turned out to be wrong. With no
    previous snapshot to return to this is a conflict, not a server error.
    """
    services.registration.get(repository_id)
    restored = services.recovery.rollback(repository_id)
    return SnapshotReference(
        snapshot_id=restored.snapshot_id,
        git_head=restored.git_head,
        working_tree_fingerprint=restored.working_tree_fingerprint,
        freshness=SnapshotFreshness.FRESH,
        semantic_coverage=0.0,
    )


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


class WatchResponse(BaseModel):
    """Whether continuous freshness is on for a repository, and how it is doing.

    `enabled` is the stored decision; `running` is the observed reality. They
    disagree when a watcher could not start — a vanished directory, exhausted
    handles — and showing only one of them would hide exactly that case.
    """

    repository_id: str
    enabled: bool
    running: bool
    pending: bool
    failure_count: int
    last_error: str | None


class WatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _watch_response(
    repository_id: str, services: ApplicationServices, request: Request
) -> WatchResponse:
    repository = services.repositories.get(repository_id)
    if repository is None:
        raise RepositoryNotFoundError("No repository matches that ID.")

    watchers: WatchService | None = getattr(request.app.state, "watchers", None)
    entry = None
    if watchers is not None:
        entry = next(
            (item for item in watchers.status() if item.repository_id == repository_id),
            None,
        )

    return WatchResponse(
        repository_id=repository_id,
        enabled=repository.watch_enabled,
        running=entry is not None and entry.running,
        pending=entry is not None and entry.pending,
        failure_count=entry.failure_count if entry else 0,
        last_error=entry.last_error if entry else None,
    )


@router.get("/{repository_id}/watch")
def get_watch(
    repository_id: str, services: Services, request: Request
) -> WatchResponse:
    """Report the watch switch and what the watcher is actually doing."""
    return _watch_response(repository_id, services, request)


@router.put("/{repository_id}/watch")
def set_watch(
    repository_id: str, body: WatchUpdate, services: Services, request: Request
) -> WatchResponse:
    """Turn continuous freshness on or off for one repository.

    The decision is persisted, so it survives a restart: turning the watcher off
    is a statement about the repository, not about this process.
    """
    watchers: WatchService | None = getattr(request.app.state, "watchers", None)
    if watchers is not None:
        watchers.set_enabled(repository_id, enabled=body.enabled)
    else:
        if services.repositories.get(repository_id) is None:
            raise RepositoryNotFoundError("No repository matches that ID.")
        services.repositories.set_watch_enabled(repository_id, enabled=body.enabled)
    return _watch_response(repository_id, services, request)
