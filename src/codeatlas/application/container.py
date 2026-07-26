"""Application service wiring.

Every delivery adapter — CLI, REST, and anything added later — builds its
services here. That is what keeps repository logic in one place rather than
letting each adapter grow its own variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection

from codeatlas.application.indexing import IndexRepositoryService
from codeatlas.application.lookup import ExactSymbolLookupService
from codeatlas.application.recovery import SnapshotRecoveryService
from codeatlas.application.registration import RegisterRepositoryService
from codeatlas.application.status import RepositoryStatusService
from codeatlas.parsing.registry import default_registry
from codeatlas.repositories.git_state import GitAdapter
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.retrieval.lexical import LexicalSearchService
from codeatlas.storage.sqlite.stores import (
    ChunkStore,
    FileStore,
    IndexJobStore,
    RepositoryStore,
    SearchStore,
    SnapshotStore,
    SymbolStore,
)


@dataclass(frozen=True)
class ApplicationServices:
    """The application surface shared by all adapters."""

    registration: RegisterRepositoryService
    indexing: IndexRepositoryService
    lookup: ExactSymbolLookupService
    status: RepositoryStatusService
    recovery: SnapshotRecoveryService
    search: LexicalSearchService


def build_services(connection: Connection) -> ApplicationServices:
    """Construct the application services for one database connection."""
    repositories = RepositoryStore(connection)
    snapshots = SnapshotStore(connection)
    files = FileStore(connection)
    symbols = SymbolStore(connection)
    jobs = IndexJobStore(connection)
    search_store = SearchStore(connection)
    chunks = ChunkStore(connection)

    recovery = SnapshotRecoveryService(
        repositories=repositories,
        snapshots=snapshots,
        search=search_store,
        connection=connection,
    )
    # Heal anything a crashed predecessor left mid-build before this process
    # serves a single query.
    recovery.recover_interrupted()

    return ApplicationServices(
        registration=RegisterRepositoryService(repositories),
        indexing=IndexRepositoryService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            jobs=jobs,
            chunks=chunks,
            search=search_store,
            scanner=RepositoryScanner(),
            git=GitAdapter(),
            registry=default_registry(),
            connection=connection,
        ),
        lookup=ExactSymbolLookupService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
        ),
        status=RepositoryStatusService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            jobs=jobs,
        ),
        recovery=recovery,
        search=LexicalSearchService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            search=search_store,
        ),
    )
