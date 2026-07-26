"""Lexical search routes.

Like the query route, these adapters validate input, call one application
service, and serialize what it returned. They select no evidence, add no claim,
and never build an FTS expression themselves — user text goes to the service,
which is the only thing allowed to turn it into a query.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from codeatlas.api.errors import request_id_for
from codeatlas.api.routers.repositories import Services
from codeatlas.contracts import QueryResponse
from codeatlas.retrieval.lexical import MAX_SEARCH_RESULTS, SearchRequest

router = APIRouter(prefix="/v1/search", tags=["search"])


def _request(
    repository_id: str, query: str, limit: int, request: Request
) -> SearchRequest:
    return SearchRequest(
        repository_id=repository_id,
        query=query,
        request_id=request_id_for(request),
        limit=limit,
    )


@router.get("/files")
def search_files(
    request: Request,
    services: Services,
    repository_id: str = Query(min_length=1, max_length=256),
    q: str = Query(max_length=4096),
    limit: int = Query(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS),
) -> QueryResponse:
    return services.search.search_files(_request(repository_id, q, limit, request))


@router.get("/symbols")
def search_symbols(
    request: Request,
    services: Services,
    repository_id: str = Query(min_length=1, max_length=256),
    q: str = Query(max_length=4096),
    limit: int = Query(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS),
) -> QueryResponse:
    return services.search.search_symbols(_request(repository_id, q, limit, request))


@router.get("/text")
def search_text(
    request: Request,
    services: Services,
    repository_id: str = Query(min_length=1, max_length=256),
    q: str = Query(max_length=4096),
    limit: int = Query(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS),
) -> QueryResponse:
    return services.search.search_text(_request(repository_id, q, limit, request))
