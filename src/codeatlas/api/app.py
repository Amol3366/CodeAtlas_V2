"""The local FastAPI application.

The API is a thin adapter: it validates input, calls an application service, and
serializes the result. All repository logic stays in the application layer so the
CLI and any future adapter answer identically.

No CORS middleware is registered and the server binds to loopback. Exposing this
service to a network would require authentication, a CSRF/CORS review, a revised
threat model, and explicit approval.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from codeatlas.api.errors import codeatlas_error_response, error_response
from codeatlas.api.routers import (
    change_analysis,
    conversations,
    entities,
    graph,
    query,
    repositories,
    search,
    stream,
)
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.watching import WatchService
from codeatlas.conversations.events import EventHub
from codeatlas.conversations.executor import RunExecutor, ThreadedRunExecutor
from codeatlas.domain.errors import CodeAtlasError, ErrorCode
from codeatlas.storage.sqlite.connection import default_database_path

API_TITLE = "CodeAtlas local API"
API_VERSION = "1.0"


def create_app(database_path: Path | None = None, *, watch: bool = True) -> FastAPI:
    """Build the application bound to one database file.

    ``watch`` starts the filesystem watchers for every repository that has not
    opted out. It defaults to on because the product's third question is "how
    current is that evidence?", and a watcher that stays off until asked answers
    it with "stale, and you were not told" (ADR-0007 decision 2). Turning it off
    is for callers that want the API without background threads.
    """
    resolved_path = database_path or default_database_path()

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        watchers: WatchService | None = None
        if watch:
            watchers = WatchService(services_factory=instance.state.services_factory)
            # A watcher that cannot start must not stop the server from serving:
            # deterministic answers over a stale index still beat no answers.
            # The failure is reported through the watch status rather than by
            # refusing to boot.
            with contextlib.suppress(OSError):
                watchers.start_all()
        instance.state.watchers = watchers
        try:
            yield
        finally:
            # Connections are per request and closed with them, so shutdown has
            # no database handle of its own to release — only the watchers and
            # the run workers.
            if watchers is not None:
                watchers.stop_all()
            runner: RunExecutor | None = getattr(instance.state, "run_executor", None)
            if runner is not None:
                # Waited on deliberately. An accepted turn has already told the
                # client it is queued, so dropping it mid-flight would leave a
                # message that never resolves and never says why.
                runner.shutdown(wait=True)

    app = FastAPI(title=API_TITLE, version=API_VERSION, lifespan=lifespan)
    app.state.database_path = resolved_path
    app.state.services_factory = _services_factory(app, resolved_path)

    app.include_router(repositories.router)
    app.include_router(query.router)
    app.include_router(search.router)
    app.include_router(entities.router)
    app.include_router(graph.router)
    app.include_router(change_analysis.router)
    app.include_router(conversations.router)
    app.include_router(stream.router)

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
) -> Callable[[], AbstractContextManager[ApplicationServices]]:
    """Return a factory yielding services bound to one request's connection.

    **One connection per request, not one per application.** A
    `sqlite3.Connection` is not safe to use from two threads at once, and
    `check_same_thread=False` removes the check rather than the hazard. FastAPI
    runs synchronous handlers on a thread pool and a browser opening the
    application issues several requests at once, so a shared connection puts two
    threads inside `execute` together. That surfaces as ``InterfaceError: bad
    parameter or other API misuse`` and — worse — as one request reading
    another's result columns, which is wrong data rather than a loud failure.

    Per *thread* is not enough either, and the reason is easy to miss: a
    synchronous dependency and the endpoint that consumes it are dispatched to
    the thread pool separately, so the services built in one thread are used in
    another. Only the request bounds both.

    Opening a SQLite connection is cheap, WAL lets readers run while a writer
    works, and the busy timeout absorbs writer contention — so for a
    single-user local service this costs little and removes a whole class of
    corruption.
    """
    hub_lock = threading.Lock()

    def hub() -> EventHub:
        # One hub for the application's lifetime. Services are rebuilt per
        # request, so a per-call hub would leave the request that streams a run
        # looking in a different registry from the one that started it. The
        # lock matters for the same reason the connection does: two concurrent
        # first requests would otherwise build two hubs and keep only one.
        existing: EventHub | None = getattr(app.state, "event_hub", None)
        if existing is not None:
            return existing
        with hub_lock:
            existing = getattr(app.state, "event_hub", None)
            if existing is None:
                existing = EventHub()
                app.state.event_hub = existing
            return existing

    executor_lock = threading.Lock()

    def executor() -> RunExecutor:
        # One pool for the application's lifetime, built lazily and by the same
        # double-checked pattern the hub uses: two concurrent first requests
        # would otherwise each build a pool and keep only one, leaking the
        # other's threads. It is handed `factory` — the very function being
        # defined — so each worker opens its own connection rather than
        # borrowing the submitting request's.
        existing: RunExecutor | None = getattr(app.state, "run_executor", None)
        if existing is not None:
            return existing
        with executor_lock:
            existing = getattr(app.state, "run_executor", None)
            if existing is None:
                existing = ThreadedRunExecutor(factory)
                app.state.run_executor = existing
            return existing

    @contextmanager
    def factory() -> Iterator[ApplicationServices]:
        connection = _open(database_path)
        try:
            yield build_services(connection, hub=hub(), executor=executor())
        finally:
            connection.close()

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
