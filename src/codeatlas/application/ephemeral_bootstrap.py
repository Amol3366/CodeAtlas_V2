"""Opening an ephemeral session on the repositories it was configured with.

An ephemeral session starts empty by design, so without this the user meets an
application with nothing in it and has to re-register by hand every run.

Registration and indexing are deliberately separate. Registration is fast, and
its failures — a path that does not exist, is not a repository, or escapes its
root — are worth reporting before the server binds. Indexing is slow, so it runs
on a background thread and reports progress the way every other index does,
through the existing job and status surfaces. Blocking the bind on it would make
the application look hung on its first run against a large repository.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import CodeAtlasError
from codeatlas.semantic.vector_store import LazyVectorStore
from codeatlas.storage.sqlite.connection import connect


@dataclass(frozen=True)
class BootstrapFailure:
    """One configured path that could not be registered, and why."""

    path: str
    code: str
    message: str


@dataclass(frozen=True)
class BootstrapOutcome:
    """What opening the session actually managed to do."""

    registered: tuple[str, ...]
    failures: tuple[BootstrapFailure, ...]


def register_repositories(
    services: ApplicationServices, paths: Sequence[str]
) -> BootstrapOutcome:
    """Register each configured path, skipping and reporting the ones that fail.

    One unusable entry must not stop the session from starting. A stale path in
    a config file is a normal state, and refusing to serve over it would make
    the whole mode fragile for no gain.
    """
    registered: list[str] = []
    failures: list[BootstrapFailure] = []

    for path in paths:
        try:
            repository = services.registration.register(
                RegisterRepositoryRequest(path=path, display_name=None)
            )
        except CodeAtlasError as error:
            failures.append(
                BootstrapFailure(
                    path=path, code=error.code.value, message=error.message
                )
            )
            continue
        registered.append(repository.repository_id)

    return BootstrapOutcome(registered=tuple(registered), failures=tuple(failures))


def index_repositories(database_path: Path, repository_ids: Sequence[str]) -> None:
    """Index each repository in turn, against its own short-lived connection.

    Sequential on purpose. SQLite takes one writer, so indexing several
    repositories at once would serialize on the write lock anyway while making
    the progress reporting harder to read.

    A failure on one repository is contained: the ones behind it still index,
    and the failure surfaces through that repository's status rather than by
    taking down the background thread and leaving the rest silently unindexed.
    """
    for repository_id in repository_ids:
        try:
            with connect(database_path) as connection:
                services = build_services(
                    connection,
                    vectors=LazyVectorStore(database_path.parent / "vectors"),
                )
                services.indexing.index(repository_id)
        except CodeAtlasError:
            continue
