"""Graph relation routes.

`direction` and `kind` are typed enumerations rather than free text, so an
unrecognized value is a validation error at the boundary instead of a silently
empty result deeper in.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request

from codeatlas.api.errors import request_id_for
from codeatlas.api.routers.repositories import Services
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.contracts import QueryResponse
from codeatlas.retrieval.graph import MAX_ALLOWED_DEPTH, TraversalLimits

router = APIRouter(prefix="/v1/symbols", tags=["graph"])

_DEFAULT_VIEW = Query(default="callers")
_DEFAULT_DEPTH = Query(default=2, ge=1, le=MAX_ALLOWED_DEPTH)

RelationView = Literal[
    "callers",
    "callees",
    "dependencies",
    "dependents",
    "exports",
    "tests",
    "documents",
    "trace",
]


@router.get("/{symbol}/relations")
def symbol_relations(
    request: Request,
    services: Services,
    symbol: str,
    repository_id: str = Query(min_length=1, max_length=256),
    view: RelationView = _DEFAULT_VIEW,
    depth: int = _DEFAULT_DEPTH,
) -> QueryResponse:
    graph_request = GraphQueryRequest(
        repository_id=repository_id,
        symbol=symbol,
        request_id=request_id_for(request),
        max_depth=depth,
        limits=TraversalLimits(max_depth=depth),
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
    }[view]
    return handler(graph_request)
