"""The local FastAPI application.

The API is a thin adapter: it validates input, calls an application service, and
serializes the result. All repository logic stays in the application layer so the
CLI and any future adapter answer identically.

No CORS middleware is registered and the server binds to loopback. Exposing this
service to a network would require authentication, a CSRF/CORS review, a revised
threat model, and explicit approval.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from codeatlas.api.errors import codeatlas_error_response, error_response
from codeatlas.api.routers import (
    change_analysis,
    entities,
    graph,
    query,
    repositories,
    search,
)
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.domain.errors import CodeAtlasError, ErrorCode
from codeatlas.storage.sqlite.connection import default_database_path

API_TITLE = "CodeAtlas local API"
API_VERSION = "1.0"


def create_app(database_path: Path | None = None) -> FastAPI:
    """Build the application bound to one database file."""
    resolved_path = database_path or default_database_path()

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        yield
        connection: sqlite3.Connection | None = getattr(
            instance.state, "connection", None
        )
        if connection is not None:
            connection.close()
            instance.state.connection = None

    app = FastAPI(title=API_TITLE, version=API_VERSION, lifespan=lifespan)
    app.state.database_path = resolved_path
    app.state.services_factory = _services_factory(app, resolved_path)

    app.include_router(repositories.router)
    app.include_router(query.router)
    app.include_router(search.router)
    app.include_router(entities.router)
    app.include_router(graph.router)
    app.include_router(change_analysis.router)

    @app.exception_handler(CodeAtlasError)
    async def handle_codeatlas_error(
        request: Request, error: CodeAtlasError
    ) -> JSONResponse:
        return codeatlas_error_response(request, error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # The default FastAPI body echoes submitted values; the envelope keeps
        # the response shape stable and the payload out of the response.
        return error_response(
            request,
            code=ErrorCode.INVALID_REQUEST,
            message="The request body or parameters are invalid.",
            retryable=False,
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, error: Exception
    ) -> JSONResponse:
        # Deliberately opaque: an unexpected failure must not leak its message,
        # a stack trace, or a local path to the client.
        return error_response(
            request,
            code=ErrorCode.INTERNAL_ERROR,
            message="An internal error occurred.",
            retryable=False,
        )

    return app


def _services_factory(
    app: FastAPI, database_path: Path
) -> Callable[[], ApplicationServices]:
    """Return a factory that reuses one connection for this application.

    Phase 1 is a single-user local service with a single writer, so one
    connection with WAL and a busy timeout is the correct shape. A connection
    pool would add contention handling that nothing yet needs.
    """

    def factory() -> ApplicationServices:
        connection: sqlite3.Connection | None = getattr(app.state, "connection", None)
        if connection is None:
            connection = _open(database_path)
            app.state.connection = connection
        return build_services(connection)

    return factory


def _open(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database_path,
        timeout=5.0,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
