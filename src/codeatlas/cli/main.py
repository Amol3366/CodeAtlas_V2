"""The CodeAtlas command-line adapter.

The CLI is a sibling of the REST adapter, not a reimplementation: both build the
same `ApplicationServices` and serialize the same contract models, which is why
`codeatlas symbol` and `POST /v1/query` return identical evidence for the same
snapshot.

Exit codes distinguish the failure classes a script needs to branch on:

===  ==================================================================
0    success
2    invalid input (bad query, already-registered repository)
3    repository or snapshot unavailable
4    partial or abstained result — the query ran but nothing was verified
5    policy failure (path safety, scan limits)
6    internal failure
===  ==================================================================
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn

from codeatlas.api.app import create_app
from codeatlas.api.web import web_assets_path
from codeatlas.application.change_analysis import ChangeAnalysisRequest
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import ChangeAnalysisReport, QueryResponse
from codeatlas.delivery import render_markdown, render_sarif
from codeatlas.domain.errors import (
    CodeAtlasError,
    ErrorCode,
    InvalidRequestError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
)
from codeatlas.domain.repository import Repository
from codeatlas.domain.semantic import EmbeddingProviderKind
from codeatlas.retrieval.graph import MAX_ALLOWED_DEPTH, TraversalLimits
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.semantic.vector_store import LazyVectorStore
from codeatlas.settings.env_file import load_env_file
from codeatlas.storage.sqlite.backup import create_backup, restore
from codeatlas.storage.sqlite.connection import connect, default_database_path
from codeatlas.storage.sqlite.upgrade import (
    UpgradePlan,
    plan_upgrade,
    upgrade_database,
)

EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 2
EXIT_UNAVAILABLE = 3
EXIT_PARTIAL = 4
EXIT_POLICY_FAILURE = 5
EXIT_INTERNAL_FAILURE = 6

_SEARCH_KINDS = ("text", "files", "symbols")

# Binding beyond loopback needs authentication, a CSRF/CORS review, a revised
# threat model, and explicit approval (`AGENTS.md` Section 25). Until that
# exists, `--host` refuses rather than exposing an unauthenticated service.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_EXIT_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: EXIT_INVALID_INPUT,
    ErrorCode.REPOSITORY_ALREADY_REGISTERED: EXIT_INVALID_INPUT,
    ErrorCode.UNSUPPORTED_QUERY_MODE: EXIT_INVALID_INPUT,
    ErrorCode.SEARCH_QUERY_INVALID: EXIT_INVALID_INPUT,
    ErrorCode.REPOSITORY_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.SNAPSHOT_NOT_READY: EXIT_UNAVAILABLE,
    ErrorCode.INDEX_IN_PROGRESS: EXIT_UNAVAILABLE,
    ErrorCode.NO_ROLLBACK_TARGET: EXIT_UNAVAILABLE,
    ErrorCode.EVIDENCE_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.FILE_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.SYMBOL_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.CHANGE_ANALYSIS_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.CHANGE_ANALYSIS_REQUIRES_GIT: EXIT_UNAVAILABLE,
    ErrorCode.GIT_REF_UNRESOLVABLE: EXIT_INVALID_INPUT,
    ErrorCode.ANALYSIS_RULES_INVALID: EXIT_INVALID_INPUT,
    ErrorCode.CONVERSATION_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.MESSAGE_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.RUN_NOT_CANCELLABLE: EXIT_UNAVAILABLE,
    ErrorCode.RUN_NOT_RETRYABLE: EXIT_UNAVAILABLE,
    ErrorCode.CONVERSATION_ARCHIVED: EXIT_UNAVAILABLE,
    ErrorCode.QUERY_TOO_LONG: EXIT_INVALID_INPUT,
    ErrorCode.REPOSITORY_HAS_CONVERSATIONS: EXIT_INVALID_INPUT,
    ErrorCode.WATCHER_UNAVAILABLE: EXIT_UNAVAILABLE,
    ErrorCode.RESTORE_INCOMPATIBLE: EXIT_INVALID_INPUT,
    ErrorCode.INTEGRITY_CHECK_FAILED: EXIT_UNAVAILABLE,
    # Unavailable rather than invalid input: nothing about the command was
    # wrong. This build simply cannot serve the database it was pointed at.
    ErrorCode.SCHEMA_VERSION_UNSUPPORTED: EXIT_UNAVAILABLE,
    # A backup that did not complete is an internal failure of an operation the
    # user asked for, not a bad request and not an unavailable resource.
    ErrorCode.BACKUP_FAILED: EXIT_INTERNAL_FAILURE,
    ErrorCode.PATH_NOT_ALLOWED: EXIT_POLICY_FAILURE,
    ErrorCode.PATH_OUTSIDE_ROOT: EXIT_POLICY_FAILURE,
    ErrorCode.SCAN_LIMIT_EXCEEDED: EXIT_POLICY_FAILURE,
    ErrorCode.INTERNAL_ERROR: EXIT_INTERNAL_FAILURE,
}

app = typer.Typer(
    help="Local repository intelligence and change assurance.",
    no_args_is_help=True,
    add_completion=False,
)
repo_app = typer.Typer(help="Manage registered repositories.", no_args_is_help=True)
app.add_typer(repo_app, name="repo")

DatabaseOption = Annotated[
    Path | None,
    typer.Option("--db", help="Database file. Defaults to the local profile path."),
]
JsonOption = Annotated[
    bool, typer.Option("--json", help="Emit machine-readable JSON.")
]


@contextmanager
def _services(database: Path | None) -> Iterator[ApplicationServices]:
    """Open the database, upgrade it if needed, and build the services.

    The upgrade is implicit here on purpose: a user who installs a new build
    should be able to run any command and have it work. It is not silent —
    it checkpoints first, and `codeatlas upgrade` reports the same thing
    deliberately for anyone who wants to look before it happens.
    """
    path = database or default_database_path()
    upgrade_database(path)
    with connect(path) as connection:
        # The vector store is passed for the same reason the API passes one:
        # without it `build_services` leaves the semantic layer unbuilt, so a
        # repository opted into `local` would index with no embeddings written
        # and report 0% coverage forever — the documented CLI workflow in
        # `docs/operations/semantic-search.md` silently doing nothing.
        # `LazyVectorStore` opens nothing until something asks it to, so a
        # deterministic-only installation still never imports the extra.
        yield build_services(
            connection, vectors=LazyVectorStore(path.parent / "vectors")
        )


def _fail(error: CodeAtlasError) -> None:
    typer.echo(f"{error.code.value}: {error.message}", err=True)
    raise typer.Exit(_EXIT_BY_CODE.get(error.code, EXIT_INTERNAL_FAILURE))


def _emit(payload: dict[str, Any] | list[Any], text: str, *, as_json: bool) -> None:
    typer.echo(json.dumps(payload, indent=2) if as_json else text)


@repo_app.command("add")
def repo_add(
    path: Annotated[str, typer.Argument(help="Path to a local repository.")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Register a local repository."""
    try:
        with _services(database) as services:
            repository = services.registration.register(
                RegisterRepositoryRequest(path=path, display_name=name)
            )
    except CodeAtlasError as error:
        _fail(error)
        return

    _emit(
        {
            "repository_id": repository.repository_id,
            "display_name": repository.display_name,
            "created_at": repository.created_at.isoformat(),
        },
        f"Registered {repository.display_name} as {repository.repository_id}",
        as_json=as_json,
    )


@repo_app.command("list")
def repo_list(database: DatabaseOption = None, as_json: JsonOption = False) -> None:
    """List registered repositories."""
    try:
        with _services(database) as services:
            repositories = services.registration.list_all()
    except CodeAtlasError as error:
        _fail(error)
        return

    payload = [
        {
            "repository_id": item.repository_id,
            "display_name": item.display_name,
            "created_at": item.created_at.isoformat(),
        }
        for item in repositories
    ]
    lines = [
        f"{item['repository_id']}  {item['display_name']}" for item in payload
    ] or ["No repositories are registered."]
    _emit(payload, "\n".join(lines), as_json=as_json)


@repo_app.command("watch")
def repo_watch(
    repository_id: Annotated[str, typer.Argument()],
    enable: Annotated[
        bool | None,
        typer.Option(
            "--enable/--disable",
            help="Turn continuous freshness on or off. Omit to report it.",
        ),
    ] = None,
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show or change whether a repository is watched for changes.

    Reporting and setting share one command because the question a user has is
    the same either way: is this repository being kept current?
    """
    try:
        with _services(database) as services:
            repository = services.repositories.get(repository_id)
            if repository is None:
                raise RepositoryNotFoundError("No repository matches that ID.")
            if enable is not None:
                services.repositories.set_watch_enabled(
                    repository_id, enabled=enable
                )
                repository = services.repositories.get(repository_id)
                assert repository is not None
    except CodeAtlasError as error:
        _fail(error)
        return

    state = "enabled" if repository.watch_enabled else "disabled"
    _emit(
        {
            "repository_id": repository_id,
            "watch_enabled": repository.watch_enabled,
        },
        f"Watching is {state} for {repository_id}",
        as_json=as_json,
    )


@app.command("index")
def index(
    repository_id: Annotated[str, typer.Argument()],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Build and activate a snapshot for a repository."""
    try:
        with _services(database) as services:
            result = services.indexing.index(repository_id)
    except CodeAtlasError as error:
        _fail(error)
        return

    snapshot = result.snapshot
    payload = {
        "job_id": result.job_id,
        "snapshot_id": snapshot.snapshot_id,
        "state": snapshot.state.value,
        "file_count": snapshot.file_count,
        "parsed_file_count": snapshot.parsed_file_count,
        "skipped_file_count": snapshot.skipped_file_count,
        "parse_error_count": snapshot.parse_error_count,
        "warnings": list(result.warnings),
    }
    _emit(
        payload,
        (
            f"Snapshot {snapshot.snapshot_id} is {snapshot.state.value}: "
            f"{snapshot.file_count} files, {snapshot.parsed_file_count} parsed, "
            f"{snapshot.parse_error_count} parse errors"
        ),
        as_json=as_json,
    )


@app.command("status")
def status(
    repository_id: Annotated[str, typer.Argument()],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show index freshness and coverage for a repository."""
    try:
        with _services(database) as services:
            result = services.status.status(repository_id)
    except CodeAtlasError as error:
        _fail(error)
        return

    snapshot = result.snapshot
    payload = {
        "repository_id": repository_id,
        "snapshot": snapshot.model_dump(mode="json") if snapshot else None,
        "file_count": result.file_count,
        "symbol_count": result.symbol_count,
        "parse_error_count": result.parse_error_count,
        "warnings": list(result.warnings),
    }
    text = (
        f"No active snapshot for {repository_id}"
        if snapshot is None
        else (
            f"Snapshot {snapshot.snapshot_id} ({snapshot.freshness.value}): "
            f"{result.file_count} files, {result.symbol_count} symbols"
        )
    )
    _emit(payload, text, as_json=as_json)


@app.command("symbol")
def symbol(
    repository_id: Annotated[str, typer.Argument()],
    query: Annotated[str, typer.Argument(help="Exact symbol name to resolve.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10)] = 10,
) -> None:
    """Resolve an exact symbol to verified file-and-line evidence."""
    try:
        with _services(database) as services:
            response = services.lookup.lookup(
                SymbolLookupRequest(
                    repository_id=repository_id,
                    query=query,
                    request_id=f"cli_{uuid.uuid4().hex}",
                    max_results=limit,
                )
            )
    except InvalidRequestError as error:
        _fail(error)
        return
    except CodeAtlasError as error:
        _fail(error)
        return

    if as_json:
        typer.echo(response.model_dump_json(indent=2))
    else:
        typer.echo(response.answer.summary)
        for item in response.evidence:
            typer.echo(
                f"  {item.file_path}:{item.start_line}-{item.end_line}"
                f"  [{item.derivation.value}]"
            )
        for warning in response.warnings:
            typer.echo(f"  warning: {warning}", err=True)

    if not response.evidence:
        # The query ran and the snapshot was valid, but nothing was verified.
        # A script must be able to tell that apart from success.
        raise typer.Exit(EXIT_PARTIAL)


@app.command("search")
def search(
    repository_id: Annotated[str, typer.Argument()],
    query: Annotated[str, typer.Argument(help="Text to search for.")],
    kind: Annotated[
        str,
        typer.Option("--kind", help="One of: text, files, symbols."),
    ] = "text",
    database: DatabaseOption = None,
    as_json: JsonOption = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=25)] = 25,
) -> None:
    """Search the active snapshot by text, path, or symbol name."""
    if kind not in _SEARCH_KINDS:
        typer.echo(
            f"INVALID_REQUEST: --kind must be one of {', '.join(_SEARCH_KINDS)}.",
            err=True,
        )
        raise typer.Exit(EXIT_INVALID_INPUT)

    try:
        with _services(database) as services:
            request = SearchRequest(
                repository_id=repository_id,
                query=query,
                request_id=f"cli_{uuid.uuid4().hex}",
                limit=limit,
            )
            method = {
                "text": services.search.search_text,
                "files": services.search.search_files,
                "symbols": services.search.search_symbols,
            }[kind]
            response = method(request)
    except CodeAtlasError as error:
        _fail(error)
        return

    if as_json:
        typer.echo(response.model_dump_json(indent=2))
    else:
        typer.echo(response.answer.summary)
        for item in response.evidence:
            typer.echo(
                f"  {item.file_path}:{item.start_line}-{item.end_line}"
                f"  [{item.derivation.value}]"
            )
        for warning in response.warnings:
            typer.echo(f"  warning: {warning}", err=True)

    if not response.evidence:
        raise typer.Exit(EXIT_PARTIAL)


@app.command("rollback")
def rollback(
    repository_id: Annotated[str, typer.Argument()],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Restore the previous snapshot as the active one."""
    try:
        with _services(database) as services:
            restored = services.recovery.rollback(repository_id)
    except CodeAtlasError as error:
        _fail(error)
        return

    _emit(
        {"repository_id": repository_id, "snapshot_id": restored.snapshot_id},
        f"Rolled back to snapshot {restored.snapshot_id}",
        as_json=as_json,
    )


# --- Graph, entity, and diagnostic commands -----------------------------------
#
# Each wraps one application service and prints the same evidence model the REST
# adapter serializes. A truncated or empty answer exits 4 (partial), so a script
# can tell a bounded answer from a complete one.


def _graph_request(
    repository_id: str, symbol_name: str, depth: int
) -> GraphQueryRequest:
    return GraphQueryRequest(
        repository_id=repository_id,
        symbol=symbol_name,
        request_id=f"cli_{uuid.uuid4().hex}",
        max_depth=depth,
        limits=TraversalLimits(max_depth=depth),
    )


def _emit_graph(response: QueryResponse, *, as_json: bool) -> None:
    if as_json:
        typer.echo(response.model_dump_json(indent=2))
    else:
        typer.echo(response.answer.summary)
        for claim in response.answer.claims:
            typer.echo(f"  {claim.text}  [{claim.derivation.value}]")
        for warning in response.warnings:
            typer.echo(f"  warning: {warning}", err=True)

    truncated = any("TRUNCATED" in warning for warning in response.warnings)
    if not response.answer.claims or truncated:
        raise typer.Exit(EXIT_PARTIAL)


def _run_graph(
    view: str,
    repository_id: str,
    symbol_name: str,
    database: Path | None,
    as_json: bool,
    depth: int,
) -> None:
    try:
        with _services(database) as services:
            handler = {
                "callers": services.graph.callers,
                "callees": services.graph.callees,
                "dependencies": services.graph.dependencies,
                "dependents": services.graph.dependents,
                "exports": services.graph.exports,
                "tests": services.graph.related_tests,
                "trace": services.graph.trace,
            }[view]
            response = handler(_graph_request(repository_id, symbol_name, depth))
    except CodeAtlasError as error:
        _fail(error)
        return
    _emit_graph(response, as_json=as_json)


@app.command("callers")
def callers(
    repository_id: Annotated[str, typer.Argument()],
    symbol_name: Annotated[str, typer.Argument(help="Symbol whose callers to find.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
    depth: Annotated[int, typer.Option("--depth", min=1, max=MAX_ALLOWED_DEPTH)] = 2,
) -> None:
    """List the symbols that call this one."""
    _run_graph("callers", repository_id, symbol_name, database, as_json, depth)


@app.command("callees")
def callees(
    repository_id: Annotated[str, typer.Argument()],
    symbol_name: Annotated[str, typer.Argument(help="Symbol whose callees to find.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
    depth: Annotated[int, typer.Option("--depth", min=1, max=MAX_ALLOWED_DEPTH)] = 2,
) -> None:
    """List the symbols this one calls."""
    _run_graph("callees", repository_id, symbol_name, database, as_json, depth)


@app.command("deps")
def deps(
    repository_id: Annotated[str, typer.Argument()],
    symbol_name: Annotated[str, typer.Argument(help="Symbol or module to inspect.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
    direction: Annotated[str, typer.Option("--direction")] = "out",
) -> None:
    """List what this symbol depends on, or what depends on it."""
    if direction not in {"in", "out"}:
        typer.echo("--direction must be 'in' or 'out'.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    view = "dependencies" if direction == "out" else "dependents"
    _run_graph(view, repository_id, symbol_name, database, as_json, 2)


@app.command("exports")
def exports(
    repository_id: Annotated[str, typer.Argument()],
    module: Annotated[str, typer.Argument(help="Module whose exports to list.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """List what a module exports."""
    _run_graph("exports", repository_id, module, database, as_json, 1)


@app.command("tests")
def related_tests(
    repository_id: Annotated[str, typer.Argument()],
    symbol_name: Annotated[str, typer.Argument(help="Symbol whose tests to find.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """List the tests that exercise this symbol."""
    _run_graph("tests", repository_id, symbol_name, database, as_json, 1)


@app.command("trace")
def trace(
    repository_id: Annotated[str, typer.Argument()],
    symbol_name: Annotated[str, typer.Argument(help="Entry point to trace from.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
    depth: Annotated[int, typer.Option("--depth", min=1, max=MAX_ALLOWED_DEPTH)] = 2,
) -> None:
    """Trace bounded relation paths from an entry point."""
    _run_graph("trace", repository_id, symbol_name, database, as_json, depth)


@app.command("evidence")
def evidence(
    repository_id: Annotated[str, typer.Argument()],
    evidence_id: Annotated[str, typer.Argument(help="Evidence ID to re-verify.")],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Re-read and re-verify one cited region."""
    try:
        with _services(database) as services:
            response = services.entities.get_evidence(repository_id, evidence_id)
    except CodeAtlasError as error:
        _fail(error)
        return

    if as_json:
        typer.echo(response.model_dump_json(indent=2))
    else:
        typer.echo(response.answer.summary)
        for item in response.evidence:
            typer.echo(f"  {item.file_path}:{item.start_line}-{item.end_line}")
        for warning in response.warnings:
            typer.echo(f"  warning: {warning}", err=True)

    if not response.evidence:
        raise typer.Exit(EXIT_PARTIAL)


@app.command("files")
def files(
    repository_id: Annotated[str, typer.Argument()],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """List the files in the active snapshot."""
    try:
        with _services(database) as services:
            snapshot = services.indexing.get_active_snapshot(repository_id)
            if snapshot is None:
                raise SnapshotNotReadyError(
                    "The repository has no active snapshot. Index it first."
                )
            payload: list[Any] = [
                {
                    "file_id": record.file_id,
                    "path": record.relative_path,
                    "language": record.language,
                    "classification": record.classification.value,
                    "lines": record.line_count,
                }
                for record in services.indexing.list_files(snapshot.snapshot_id)
            ]
    except CodeAtlasError as error:
        _fail(error)
        return

    _emit(
        payload,
        "\n".join(f"{item['path']}  [{item['language']}]" for item in payload),
        as_json=as_json,
    )


@app.command("diagnostics")
def diagnostics(
    repository_id: Annotated[str, typer.Argument()],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Report indexing diagnostics for the repository."""
    try:
        with _services(database) as services:
            report = services.status.diagnostics(repository_id)
    except CodeAtlasError as error:
        _fail(error)
        return

    payload: dict[str, Any] = {
        "repository_id": report.repository_id,
        "snapshot_id": report.snapshot_id,
        "skipped_by_reason": dict(report.skipped_by_reason),
        "parse_error_count": report.parse_error_count,
        "warnings": list(report.warnings),
    }
    _emit(
        payload,
        "\n".join(f"{key}: {value}" for key, value in payload.items()),
        as_json=as_json,
    )


@repo_app.command("remove")
def repo_remove(
    repository_id: Annotated[str, typer.Argument()],
    cascade: Annotated[
        bool,
        typer.Option(
            "--cascade",
            help="Also delete the repository's conversations.",
        ),
    ] = False,
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove a repository from CodeAtlas. Source files are never touched.

    Refuses while conversations exist unless `--cascade` is given: the schema
    would take them along silently, and freeing an index should not cost a user
    their chat history without them saying so.
    """
    try:
        with _services(database) as services:
            services.registration.delete(repository_id, cascade=cascade)
    except CodeAtlasError as error:
        _fail(error)
        return

    _emit(
        {"repository_id": repository_id, "removed": True},
        f"Removed {repository_id}. The source files were not touched.",
        as_json=as_json,
    )


@app.command("serve")
def serve(
    web: Annotated[
        bool,
        typer.Option("--web", help="Also serve the built web application."),
    ] = False,
    host: Annotated[
        str, typer.Option("--host", help="Interface to bind. Loopback only.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 8000,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open a browser once the server starts.")
    ] = False,
    database: DatabaseOption = None,
) -> None:
    """Run the local API, optionally serving the web application with it.

    `--web` is what a packaged build runs: there is no Vite to proxy, so the API
    serves the built assets itself and the browser sees one origin — which is
    what lets the API keep its no-CORS, loopback-only posture.

    The URL is printed rather than opened. Starting a server should not steal
    focus, and it must not try to in a script or on a headless machine; `--open`
    is there for the user who wants it.
    """
    if host not in _LOOPBACK_HOSTS:
        typer.echo(
            "INVALID_REQUEST: --host must be a loopback address. Binding beyond"
            " loopback needs authentication, a CORS review, and explicit"
            " approval.",
            err=True,
        )
        raise typer.Exit(EXIT_INVALID_INPUT)

    assets: Path | None = None
    if web:
        assets = web_assets_path()
        if assets is None:
            # Serving an API-only server after `--web` was asked for would be a
            # quiet lie: the user would meet an empty page and no explanation.
            typer.echo(
                "INVALID_REQUEST: the web application has not been built."
                " Run `pnpm --dir apps/web build`, or use a packaged release.",
                err=True,
            )
            raise typer.Exit(EXIT_INVALID_INPUT)

    resolved = database or default_database_path()
    # Upgrade before listening: a first run must not answer requests against an
    # unmigrated database, and a database from a newer build must stop the
    # server here rather than fail one request at a time.
    try:
        upgrade_database(resolved)
    except CodeAtlasError as error:
        _fail(error)
        return

    application = create_app(resolved, web_assets=assets)
    url = f"http://{host}:{port}"
    typer.echo(
        f"CodeAtlas is listening on {url}"
        + (" — open it in a browser." if web else " (API only).")
    )

    if open_browser:
        # A browser that will not open is not a reason to refuse to serve.
        with contextlib.suppress(OSError):
            webbrowser.open(url)

    # `access_log=False` for two reasons that happen to agree.
    #
    # It is what `CLAUDE.md` Section 17 asks for: the access log records a
    # request path per request, and this product writes no logs by default.
    #
    # It is also a deadlock this server had. uvicorn writes that line
    # synchronously **on the event-loop thread**. A server launched by a
    # shortcut, a wrapper script, or a test harness usually gets a pipe for
    # stdout that nobody reads; a pipe holds a few kilobytes, and the write
    # that fills it blocks forever. Not one request — every request, with the
    # process alive and nothing in the log to say why (found in P6-08).
    uvicorn.run(application, host=host, port=port, access_log=False)


@app.command("backup")
def backup(
    destination: Annotated[
        Path, typer.Argument(help="Where to write the backup file.")
    ],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Copy the database to a file, verifying the copy before keeping it.

    Safe to run while CodeAtlas is running: the copy goes through SQLite's
    online backup API rather than the filesystem, because in WAL mode a file
    copy can miss recent commits or capture a torn page.
    """
    source = database or default_database_path()
    try:
        result = create_backup(source, destination)
    except CodeAtlasError as error:
        _fail(error)
        return

    _emit(
        {
            "path": str(result.path),
            "schema_version": result.schema_version,
            "size_bytes": result.size_bytes,
        },
        f"Backed up to {result.path} ({result.size_bytes} bytes).",
        as_json=as_json,
    )


@app.command("restore")
def restore_command(
    backup_path: Annotated[
        Path, typer.Argument(help="The backup file to restore from.")
    ],
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Replace the database with a backup, after validating it.

    Offline by design: stop CodeAtlas first. Swapping the file underneath a
    serving process is a reliable way to corrupt it, so this refuses while the
    database is in use. Schema version and integrity are checked against the
    backup *before* anything is replaced, and the database being replaced is
    kept beside it.
    """
    target = database or default_database_path()
    try:
        result = restore(backup_path, target)
    except CodeAtlasError as error:
        _fail(error)
        return

    kept = (
        f" The previous database was kept at {result.replaced_path}."
        if result.replaced_path is not None
        else ""
    )
    _emit(
        {
            "restored": True,
            "path": str(result.path),
            "schema_version": result.schema_version,
            "replaced_path": (
                None if result.replaced_path is None else str(result.replaced_path)
            ),
        },
        f"Restored {result.path}.{kept} Start CodeAtlas to use it.",
        as_json=as_json,
    )


@app.command("upgrade")
def upgrade(
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Bring the database up to the schema this build understands.

    Every command upgrades on open, so this is rarely required. It exists
    because an upgrade of a long history is worth being able to inspect and to
    have a record of: which version was found, which migrations ran, and where
    the checkpoint taken beforehand was written.

    A database from a *newer* build is refused. Migrations are forward-only, so
    there is no honest way to read a schema this build has never seen.
    """
    target = database or default_database_path()
    try:
        result = upgrade_database(target)
    except CodeAtlasError as error:
        _fail(error)
        return

    checkpoint = (
        None if result.checkpoint_path is None else str(result.checkpoint_path)
    )
    if result.upgraded:
        summary = (
            f"Upgraded {result.path} from schema {result.from_version} to"
            f" {result.to_version}."
        )
        if checkpoint is not None:
            summary += f" The database as it was is kept at {checkpoint}."
        preserved = ", ".join(
            f"{count} {table}" for table, count in sorted(result.counts.items())
        )
        summary += f"\nPreserved: {preserved}."
    else:
        summary = (
            f"{result.path} is already at schema {result.to_version}."
            " Nothing to upgrade."
        )
    for warning in result.warnings:
        summary += f"\nWarning: {warning}. Restore the checkpoint to compare."

    _emit(
        {
            "upgraded": result.upgraded,
            "path": str(result.path),
            "from_version": result.from_version,
            "to_version": result.to_version,
            "applied": list(result.applied),
            "checkpoint_path": checkpoint,
            "counts": dict(result.counts),
            "warnings": list(result.warnings),
        },
        summary,
        as_json=as_json,
    )


@app.command("purge")
def purge(
    older_than_days: Annotated[
        int,
        typer.Option(
            "--older-than-days",
            help="Purge conversations deleted at least this many days ago.",
        ),
    ] = 30,
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Permanently remove conversations that were deleted long enough ago.

    `--older-than-days 0` means "everything already deleted, gone now". An
    undeleted conversation is never touched, whatever the window.
    """
    if older_than_days < 0:
        typer.echo(
            "INVALID_REQUEST: --older-than-days cannot be negative.", err=True
        )
        raise typer.Exit(EXIT_INVALID_INPUT)

    try:
        with _services(database) as services:
            removed = services.conversations.purge_deleted(
                older_than=timedelta(days=older_than_days)
            )
    except CodeAtlasError as error:
        _fail(error)
        return

    _emit(
        {"purged": removed, "older_than_days": older_than_days},
        f"Purged {removed} deleted conversation(s).",
        as_json=as_json,
    )


@app.command("doctor")
def doctor(
    repository_id: Annotated[
        str | None,
        typer.Argument(help="Repository to check. Omit to check every one."),
    ] = None,
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Report the health of the installation and its repositories.

    The product's fifth question — "what does CodeAtlas not know?" — asked
    about the installation rather than about a query. Its most useful answer is
    the one recovery leaves behind: an index run that was interrupted, or one
    that no live process owns and that is quietly blocking every reindex.

    Exit code 4 means problems were found. That is a different fact from the
    command failing, and a script needs to tell them apart.
    """
    # Planned before opening, because opening is what performs the upgrade.
    # Reporting the version doctor *caused* would answer a question nobody
    # asked.
    plan = plan_upgrade(database or default_database_path())
    try:
        with _services(database) as services:
            repositories = (
                [services.registration.get(repository_id)]
                if repository_id is not None
                else services.repositories.list_all()
            )
            entries = [_doctor_entry(services, item) for item in repositories]
    except CodeAtlasError as error:
        _fail(error)
        return

    healthy = all(not entry["problems"] for entry in entries)
    payload: dict[str, Any] = {
        "healthy": healthy,
        "schema": {
            "found_version": plan.current_version,
            "expected_version": plan.target_version,
            "pending": list(plan.pending),
        },
        "repositories": entries,
    }
    _emit(payload, _doctor_text(entries, plan, healthy=healthy), as_json=as_json)
    if not healthy:
        raise typer.Exit(EXIT_PARTIAL)


def _doctor_entry(
    services: ApplicationServices, repository: Repository
) -> dict[str, Any]:
    repository_id = repository.repository_id
    status_result = services.status.status(repository_id)
    report = services.status.diagnostics(repository_id)

    problems: list[str] = []
    if not Path(repository.canonical_root).is_dir():
        # Diagnosis must not require the thing being diagnosed to be healthy.
        problems.append("ROOT_MISSING")
    if status_result.snapshot is None:
        problems.append("NEVER_INDEXED")
    if report.interrupted_run is not None:
        problems.append("INDEX_RUN_INTERRUPTED")
    if report.open_jobs:
        # Either a run genuinely in flight or one whose owner cannot be
        # verified. Both block a reindex, and from outside they look the same
        # — which is exactly why the owner is printed.
        problems.append("INDEX_RUN_IN_PROGRESS")
    if report.parse_error_count:
        problems.append("PARSE_ERRORS")

    interrupted = report.interrupted_run
    return {
        "repository_id": repository_id,
        "display_name": repository.display_name,
        "watch_enabled": repository.watch_enabled,
        "active_snapshot_id": (
            None
            if status_result.snapshot is None
            else status_result.snapshot.snapshot_id
        ),
        "file_count": status_result.file_count,
        "symbol_count": status_result.symbol_count,
        "parse_error_count": report.parse_error_count,
        "interrupted_run": (
            None
            if interrupted is None
            else {
                "snapshot_id": interrupted.snapshot_id,
                "stage": interrupted.stage,
                "started_at": interrupted.started_at,
                "recovered_at": interrupted.recovered_at,
            }
        ),
        "open_jobs": [
            {
                "job_id": job.job_id,
                "stage": job.stage,
                "started_at": job.started_at,
                "owner_pid": job.owner_pid,
            }
            for job in report.open_jobs
        ],
        "warnings": list(report.warnings),
        "problems": problems,
    }


def _doctor_text(
    entries: list[dict[str, Any]], plan: UpgradePlan, *, healthy: bool
) -> str:
    lines = ["CodeAtlas doctor"]
    if plan.is_required:
        lines.append(
            f"  schema {plan.current_version} found, {plan.target_version} expected"
            f" — upgraded on open (migrations {list(plan.pending)})"
        )
    else:
        lines.append(f"  schema {plan.target_version}, up to date")

    if not entries:
        lines.append("  No repositories are registered.")
        return "\n".join(lines)

    for entry in entries:
        lines.append(f"\n{entry['display_name']}  [{entry['repository_id']}]")
        snapshot = entry["active_snapshot_id"]
        lines.append(
            f"  snapshot: {snapshot or 'none'}"
            f"  files: {entry['file_count']}  symbols: {entry['symbol_count']}"
        )
        lines.append(f"  watching: {'on' if entry['watch_enabled'] else 'off'}")

        interrupted = entry["interrupted_run"]
        if interrupted is not None:
            lines.append(
                f"  last index was interrupted during {interrupted['stage']}"
                f" (recovered {interrupted['recovered_at']}); reindex to refresh"
            )
        for job in entry["open_jobs"]:
            owner = job["owner_pid"]
            lines.append(
                f"  an index run is open: {job['job_id']} at {job['stage']},"
                f" owned by pid {owner if owner is not None else 'unknown'}"
            )
        if not entry["problems"]:
            lines.append("  ok")
        else:
            lines.append(f"  problems: {', '.join(entry['problems'])}")

    lines.append("\nHealthy." if healthy else "\nProblems were found.")
    return "\n".join(lines)


@app.command("impact")
def impact(
    repository_id: Annotated[str, typer.Argument(help="Repository to analyze.")],
    base: Annotated[str, typer.Option("--base", help="Base ref.")] = "HEAD",
    commits: Annotated[
        str | None,
        typer.Option(
            "--commits",
            help="Analyze a commit range instead of the working tree, as A..B.",
        ),
    ] = None,
    report_format: Annotated[
        str, typer.Option("--format", help="json, markdown, or sarif.")
    ] = "markdown",
    database: DatabaseOption = None,
) -> None:
    """Analyze a working tree or commit range and print the report.

    Exit code 4 means the analysis ran and found nothing to report, which is a
    different fact from a failure and scripts need to tell them apart.
    """
    if report_format not in {"json", "markdown", "sarif"}:
        typer.echo(
            "INVALID_REQUEST: --format must be json, markdown, or sarif.", err=True
        )
        raise typer.Exit(EXIT_INVALID_INPUT)

    with _services(database) as services:
        try:
            if commits is None:
                report = services.change_analysis.analyze_working_tree(
                    ChangeAnalysisRequest(
                        repository_id=repository_id,
                        base_ref=base,
                        request_id=f"cli_{uuid.uuid4().hex}",
                    )
                )
            else:
                base_ref, _, target_ref = commits.partition("..")
                if not base_ref or not target_ref:
                    raise InvalidRequestError(
                        "--commits must be given as BASE..TARGET."
                    )
                report = services.change_analysis.analyze_commit_range(
                    ChangeAnalysisRequest(
                        repository_id=repository_id,
                        base_ref=base_ref,
                        target_ref=target_ref,
                        request_id=f"cli_{uuid.uuid4().hex}",
                    )
                )
        except CodeAtlasError as error:
            _fail(error)
            return

        _print_report(report, report_format)
        if not report.findings:
            raise typer.Exit(EXIT_PARTIAL)


@app.command("analysis")
def analysis(
    analysis_id: Annotated[str, typer.Argument(help="A stored analysis ID.")],
    report_format: Annotated[
        str, typer.Option("--format", help="json, markdown, or sarif.")
    ] = "markdown",
    database: DatabaseOption = None,
) -> None:
    """Print a stored analysis. Reads the same rows every adapter reads."""
    if report_format not in {"json", "markdown", "sarif"}:
        typer.echo(
            "INVALID_REQUEST: --format must be json, markdown, or sarif.", err=True
        )
        raise typer.Exit(EXIT_INVALID_INPUT)

    with _services(database) as services:
        try:
            report = services.change_analysis.get(analysis_id)
        except CodeAtlasError as error:
            _fail(error)
            return
        _print_report(report, report_format)


def _print_report(report: ChangeAnalysisReport, report_format: str) -> None:
    if report_format == "markdown":
        typer.echo(render_markdown(report))
    elif report_format == "sarif":
        typer.echo(json.dumps(render_sarif(report), indent=2))
    else:
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2))


def main() -> None:
    """Console-script entry point."""
    # Deliberately here and not in `app()`. Tests invoke the Typer app directly
    # and must not pick up a developer's real `.env`; the console script is the
    # thing a user runs.
    load_env_file()
    try:
        app()
    except sqlite3.Error:
        typer.echo("INTERNAL_ERROR: the local database could not be used.", err=True)
        raise typer.Exit(EXIT_INTERNAL_FAILURE) from None
@app.command("settings")
def settings_command(
    repository_id: Annotated[str, typer.Argument()],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Embedding provider: none, local, or openai.",
        ),
    ] = None,
    monthly_budget: Annotated[
        int | None,
        typer.Option("--monthly-budget", help="Monthly token budget."),
    ] = None,
    per_run_budget: Annotated[
        int | None,
        typer.Option("--per-run-budget", help="Per-run token budget."),
    ] = None,
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show or change one repository's provider settings.

    With no options this only reads. Every rule about what may be enabled lives
    in the application service, so this command and `PATCH /v1/settings` refuse
    exactly the same things — a CLI that could enable a transmitting provider on
    easier terms would make the opt-in a suggestion.
    """
    kind: EmbeddingProviderKind | None = None
    if provider is not None:
        try:
            kind = EmbeddingProviderKind(provider)
        except ValueError:
            typer.echo(
                f"INVALID_REQUEST: unknown provider '{provider}'."
                " Choose none, local, or openai.",
                err=True,
            )
            raise typer.Exit(EXIT_INVALID_INPUT) from None

    changing = (
        kind is not None or monthly_budget is not None or per_run_budget is not None
    )
    try:
        with _services(database) as services:
            result = (
                services.settings.update(
                    repository_id,
                    embedding_provider=kind,
                    monthly_token_budget=monthly_budget,
                    per_run_token_budget=per_run_budget,
                )
                if changing
                else services.settings.get(repository_id)
            )
    except CodeAtlasError as error:
        _fail(error)
        return

    payload = {
        "repository_id": result.repository_id,
        "embedding_provider": result.embedding_provider.value,
        "monthly_token_budget": result.monthly_token_budget,
        "per_run_token_budget": result.per_run_token_budget,
        "transmits_off_machine": result.transmits_off_machine,
        "updated_at": result.updated_at.isoformat(),
    }
    transmits = " (transmits off machine)" if result.transmits_off_machine else ""
    text = (
        f"{result.repository_id}: provider={result.embedding_provider.value}"
        f"{transmits}, monthly={result.monthly_token_budget},"
        f" per-run={result.per_run_token_budget}"
    )
    _emit(payload, text, as_json=as_json)


@app.command("models")
def models_command(
    database: DatabaseOption = None,
    as_json: JsonOption = False,
) -> None:
    """List embedding providers and whether each can run on this machine.

    Unavailable providers are listed too, with what they need. Hiding them
    would leave a user unable to discover that installing an extra is all that
    stands between them and the feature.
    """
    try:
        with _services(database) as services:
            models = services.settings.models()
    except CodeAtlasError as error:
        _fail(error)
        return

    payload = {
        "models": [
            {
                "provider": model.provider.value,
                "model_id": model.model_id,
                "dimensions": model.dimensions,
                "available": model.available,
                "transmits_off_machine": model.transmits_off_machine,
                "requires": model.requires,
            }
            for model in models
        ]
    }
    lines = []
    for model in models:
        state = "available" if model.available else f"needs {model.requires}"
        transmits = (
            "transmits off machine"
            if model.transmits_off_machine
            else "local only"
        )
        lines.append(f"{model.provider.value}: {state}; {transmits}")
    _emit(payload, "\n".join(lines), as_json=as_json)


if __name__ == "__main__":
    main()
