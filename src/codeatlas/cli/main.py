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

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import (
    CodeAtlasError,
    ErrorCode,
    InvalidRequestError,
)
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect, default_database_path
from codeatlas.storage.sqlite.migrations import apply_migrations

EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 2
EXIT_UNAVAILABLE = 3
EXIT_PARTIAL = 4
EXIT_POLICY_FAILURE = 5
EXIT_INTERNAL_FAILURE = 6

_SEARCH_KINDS = ("text", "files", "symbols")

_EXIT_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: EXIT_INVALID_INPUT,
    ErrorCode.REPOSITORY_ALREADY_REGISTERED: EXIT_INVALID_INPUT,
    ErrorCode.UNSUPPORTED_QUERY_MODE: EXIT_INVALID_INPUT,
    ErrorCode.SEARCH_QUERY_INVALID: EXIT_INVALID_INPUT,
    ErrorCode.REPOSITORY_NOT_FOUND: EXIT_UNAVAILABLE,
    ErrorCode.SNAPSHOT_NOT_READY: EXIT_UNAVAILABLE,
    ErrorCode.INDEX_IN_PROGRESS: EXIT_UNAVAILABLE,
    ErrorCode.NO_ROLLBACK_TARGET: EXIT_UNAVAILABLE,
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
    """Open the database, apply migrations, and build the services."""
    path = database or default_database_path()
    with connect(path) as connection:
        apply_migrations(connection)
        yield build_services(connection)


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


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except sqlite3.Error:
        typer.echo("INTERNAL_ERROR: the local database could not be used.", err=True)
        raise typer.Exit(EXIT_INTERNAL_FAILURE) from None


if __name__ == "__main__":
    main()
