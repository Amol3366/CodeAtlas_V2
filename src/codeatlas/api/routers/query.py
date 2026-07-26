"""Repository intelligence query routes.

One endpoint over the services that already exist, not a second pipeline. Each
mode dispatches to exactly one application service, and `QueryResponse` is
returned exactly as that service produced it: the adapter chooses no evidence,
adds no claim, and rewrites no warning.

An unrecognized mode is refused with the supported list rather than silently
falling back to a default — a client asking for something CodeAtlas cannot do
should be told so, not quietly answered a different question.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.api.errors import request_id_for
from codeatlas.api.routers.repositories import Services
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.application.lookup import MAX_RESULTS, SymbolLookupRequest
from codeatlas.contracts import QueryResponse
from codeatlas.domain.errors import UnsupportedQueryModeError
from codeatlas.retrieval.graph import MAX_ALLOWED_DEPTH, TraversalLimits
from codeatlas.retrieval.lexical import MAX_SEARCH_RESULTS, SearchRequest

router = APIRouter(prefix="/v1", tags=["query"])

QueryMode = Literal[
    "exact_symbol",
    "symbol",
    "text",
    "files",
    "callers",
    "callees",
    "dependencies",
    "dependents",
    "exports",
    "tests",
    "documents",
    "trace",
]

SUPPORTED_MODES: tuple[str, ...] = (
    "exact_symbol",
    "symbol",
    "text",
    "files",
    "callers",
    "callees",
    "dependencies",
    "dependents",
    "exports",
    "tests",
    "documents",
    "trace",
)

_GRAPH_MODES = frozenset(
    {
        "callers",
        "callees",
        "dependencies",
        "dependents",
        "exports",
        "tests",
        "documents",
        "trace",
    }
)
_SEARCH_MODES = frozenset({"text", "files"})


class QueryBody(BaseModel):
    """A bounded query request."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(min_length=1, max_length=256)
    query: str = Field(max_length=4096)
    # Deliberately `str`, not the Literal, so an unknown mode reaches the
    # handler and is refused with a listed set of alternatives rather than
    # producing an opaque 422 that names no supported mode.
    mode: str = "exact_symbol"
    max_results: int = Field(default=MAX_RESULTS, ge=1, le=MAX_RESULTS)
    depth: int = Field(default=2, ge=1, le=MAX_ALLOWED_DEPTH)


@router.post("/query")
def query(body: QueryBody, request: Request, services: Services) -> QueryResponse:
    if body.mode not in SUPPORTED_MODES:
        raise UnsupportedQueryModeError(
            f"'{body.mode}' is not a supported query mode.",
            details={"supported_modes": ", ".join(SUPPORTED_MODES)},
        )

    request_id = request_id_for(request)

    if body.mode in {"exact_symbol", "symbol"}:
        return services.lookup.lookup(
            SymbolLookupRequest(
                repository_id=body.repository_id,
                query=body.query,
                request_id=request_id,
                max_results=body.max_results,
            )
        )

    if body.mode in _SEARCH_MODES:
        search_request = SearchRequest(
            repository_id=body.repository_id,
            query=body.query,
            request_id=request_id,
            limit=min(body.max_results, MAX_SEARCH_RESULTS),
        )
        if body.mode == "files":
            return services.search.search_files(search_request)
        return services.search.search_text(search_request)

    graph_request = GraphQueryRequest(
        repository_id=body.repository_id,
        symbol=body.query,
        request_id=request_id,
        max_depth=body.depth,
        limits=TraversalLimits(max_depth=body.depth),
    )
    handler = {
        "callers": services.graph.callers,
        "callees": services.graph.callees,
        "dependencies": services.graph.dependencies,
        "dependents": services.graph.dependents,
        "exports": services.graph.exports,
        "tests": services.graph.related_tests,
        "documents": services.graph.related_documents,
        "trace": services.graph.trace,
    }[body.mode]
    return handler(graph_request)
