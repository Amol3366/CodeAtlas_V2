"""Repository intelligence query routes.

`QueryResponse` is returned exactly as the application service produced it. The
adapter chooses no evidence, adds no claim, and rewrites no warning.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.api.errors import request_id_for
from codeatlas.api.routers.repositories import Services
from codeatlas.application.lookup import MAX_RESULTS, SymbolLookupRequest
from codeatlas.contracts import QueryResponse
from codeatlas.domain.errors import UnsupportedQueryModeError

router = APIRouter(prefix="/v1", tags=["query"])

SUPPORTED_MODES = ("exact_symbol",)


class QueryBody(BaseModel):
    """A bounded query request."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(min_length=1, max_length=256)
    query: str = Field(max_length=4096)
    mode: Literal["exact_symbol"] | str = "exact_symbol"
    max_results: int = Field(default=MAX_RESULTS, ge=1, le=MAX_RESULTS)


@router.post("/query")
def query(body: QueryBody, request: Request, services: Services) -> QueryResponse:
    if body.mode not in SUPPORTED_MODES:
        raise UnsupportedQueryModeError(
            "Phase 1 supports only the 'exact_symbol' query mode.",
            details={"supported_modes": ", ".join(SUPPORTED_MODES)},
        )

    return services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=body.repository_id,
            query=body.query,
            request_id=request_id_for(request),
            max_results=body.max_results,
        )
    )
