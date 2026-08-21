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
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from codeatlas.api.errors import codeatlas_error_response, error_response
from codeatlas.api.routers import (
    change_analysis,
    conversations,
    entities,
    graph,
    query,
    repositories,
    search,
    settings,
    stream,
)
from codeatlas.api.web import mount_web_application
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.watching import WatchService
from codeatlas.conversations.events import EventHub
from codeatlas.conversations.executor import RunExecutor, ThreadedRunExecutor
from codeatlas.domain.errors import CodeAtlasError, ErrorCode
from codeatlas.semantic.vector_store import LazyVectorStore, VectorStore
from codeatlas.settings.env_file import load_env_file
from codeatlas.storage.sqlite.connection import default_database_path

API_TITLE = "CodeAtlas local API"
API_VERSION = "1.0"

# Transport-level failures that never reach a route, mapped to the contract's
# codes. A route that *does* run raises a `CodeAtlasError` and is handled above;
# these are the ones Starlette answers on its own.
_API_FAILURES: dict[int, tuple[ErrorCode, str]] = {
    404: (ErrorCode.INVALID_REQUEST, "No such endpoint."),
    405: (ErrorCode.INVALID_REQUEST, "That method is not allowed here."),
}


def create_app(
    database_path: Path | None = None,
    *,
    watch: bool = True,
    web_assets: Path | None = None,
) -> FastAPI:
    """Build the application bound to one database file.

    ``web_assets`` serves the built web application from this process, which is
    what a packaged build does: there is no Vite to proxy, so the API answers
    both `/v1` and the shell and the browser still sees one origin.

    ``watch`` starts the filesystem watchers for every repository that has not
    opted out. It defaults to on because the product's third question is "how
    current is that evidence?", and a watcher that stays off until asked answers
    it with "stale, and you were not told" (ADR-0007 decision 2). Turning it off
    is for callers that want the API without background threads.
    """
    # Before anything reads the environment. `describe_available_providers`
    # decides whether the settings surface may offer OpenAI by looking for
    # OPENAI_API_KEY, and it must see what `.env` supplies. Idempotent, so a
    # process that also ran the CLI loses nothing.
    load_env_file()

    resolved_path = database_path or default_database_path()

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        # Retention runs once, here, and never on the request path. A sweep on
        # every request would put a delete-and-vacuum on the hot path for a
        # policy measured in days; an unattended install is covered by its next
        # restart, which is the trade ADR-0007 decision 5 accepted. A failure
        # must not stop the server from serving: stale deleted rows are a
        # housekeeping problem, an unavailable API is not.
        with (
            contextlib.suppress(Exception),
            instance.state.services_factory() as services,
        ):
            services.conversations.purge_deleted()

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
    app.state.vector_store = LazyVectorStore(resolved_path.parent / "vectors")
    # Recorded so a caller can see what was mounted without inspecting routes.
    app.state.web_assets = web_assets
    app.state.services_factory = _services_factory(app, resolved_path)

    app.include_router(repositories.router)
    app.include_router(query.router)
    app.include_router(search.router)
    app.include_router(entities.router)
    app.include_router(graph.router)
    app.include_router(change_analysis.router)
    app.include_router(conversations.router)
    app.include_router(conversations.message_router)
    app.include_router(settings.router)
    app.include_router(stream.router)

    # Mounted after every router, so no API route can be shadowed by a file
    # that happens to share its path.
    if web_assets is not None:
        mount_web_application(app, web_assets)

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

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, error: StarletteHTTPException
    ) -> Response:
        """Give unmatched and unsupported `/v1` requests the error envelope.

        Starlette answers an unknown route with a bare status and no body. A
        client that always reads `error.code` then meets a parse failure
        instead of a stable code — the same complaint the SPA fallback rule
        exists to prevent, one layer further in (`CLAUDE.md` Section 12.6).

        Only `/v1` is translated. Outside it the plain response is what the
        static mount and the client-side route fallback depend on.
        """
        if not request.url.path.startswith("/v1"):
            # Starlette's own default, reproduced rather than imported: the
            # helper that used to expose it is not part of its public surface.
            if error.status_code in {204, 304}:
                return Response(status_code=error.status_code, headers=error.headers)
            return PlainTextResponse(
                error.detail, status_code=error.status_code, headers=error.headers
            )

        code, message = _API_FAILURES.get(
            error.status_code,
            (ErrorCode.INVALID_REQUEST, "The request could not be handled."),
        )
        return error_response(
            request,
            code=code,
            message=message,
            retryable=False,
            status_code=error.status_code,
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
            vectors: VectorStore = app.state.vector_store
            yield build_services(
                connection,
                hub=hub(),
                executor=executor(),
                vectors=vectors,
            )
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
