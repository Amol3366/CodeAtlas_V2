"""Addressable entity routes: evidence, files, and symbols by ID.

Each route validates input, calls one application service, and serializes what
it returned. An unknown ID is a 404 with a stable code, never an empty success
that a client could mistake for "exists but has nothing".
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from codeatlas.api.routers.repositories import Services
from codeatlas.application.entities import FileDetail, SymbolDetail
from codeatlas.contracts import QueryResponse

router = APIRouter(prefix="/v1", tags=["entities"])


@router.get("/evidence/{evidence_id}")
def get_evidence(
    request: Request,
    services: Services,
    evidence_id: str,
    repository_id: str = Query(min_length=1, max_length=256),
) -> QueryResponse:
    """Re-verify a stored evidence region against the file on disk."""
    return services.entities.get_evidence(repository_id, evidence_id)


@router.get("/files/{file_id}")
def get_file(
    request: Request,
    services: Services,
    file_id: str,
    repository_id: str = Query(min_length=1, max_length=256),
) -> FileDetail:
    return services.entities.get_file(repository_id, file_id)


@router.get("/symbols/{symbol_id}")
def get_symbol(
    request: Request,
    services: Services,
    symbol_id: str,
    repository_id: str = Query(min_length=1, max_length=256),
) -> SymbolDetail:
    return services.entities.get_symbol(repository_id, symbol_id)
