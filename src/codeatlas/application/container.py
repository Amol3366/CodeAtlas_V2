"""Application service wiring.

Every delivery adapter — CLI, REST, and anything added later — builds its
services here. That is what keeps repository logic in one place rather than
letting each adapter grow its own variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection

from codeatlas.application.change_analysis import ChangeAnalysisService
from codeatlas.application.entities import EntityService
from codeatlas.application.graph_queries import GraphQueryService
from codeatlas.application.indexing import IndexRepositoryService
from codeatlas.application.lookup import ExactSymbolLookupService
from codeatlas.application.recovery import SnapshotRecoveryService
from codeatlas.application.registration import RegisterRepositoryService
from codeatlas.application.status import RepositoryStatusService
from codeatlas.parsing.registry import default_registry
from codeatlas.repositories.git_diff import GitDiffAdapter
from codeatlas.repositories.git_state import GitAdapter
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.retrieval.lexical import LexicalSearchService
from codeatlas.storage.sqlite.stores import (
    ChangeAnalysisStore,
    ChunkStore,
    EvidenceStore,
    FileStore,
    IndexJobStore,
    RelationStore,
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
    graph: GraphQueryService
    entities: EntityService
    change_analysis: ChangeAnalysisService


def build_services(connection: Connection) -> ApplicationServices:
    """Construct the application services for one database connection."""
    repositories = RepositoryStore(connection)
    snapshots = SnapshotStore(connection)
    files = FileStore(connection)
    symbols = SymbolStore(connection)
    jobs = IndexJobStore(connection)
    search_store = SearchStore(connection)
    chunks = ChunkStore(connection)
    relations = RelationStore(connection)
    evidence = EvidenceStore(connection)
    analyses = ChangeAnalysisStore(connection)

    recovery = SnapshotRecoveryService(
        repositories=repositories,
        snapshots=snapshots,
        search=search_store,
        connection=connection,
    )
    # Heal anything a crashed predecessor left mid-build before this process
    # serves a single query.
    recovery.recover_interrupted()

    # Hoisted because change analysis re-indexes before it compares: its
    # freshness gate needs the same indexing service every other adapter uses,
    # not a second one with its own state.
    indexing = IndexRepositoryService(
        repositories=repositories,
        snapshots=snapshots,
        files=files,
        symbols=symbols,
        jobs=jobs,
        chunks=chunks,
        search=search_store,
        relations=relations,
        scanner=RepositoryScanner(),
        git=GitAdapter(),
        registry=default_registry(),
        connection=connection,
    )

    return ApplicationServices(
        registration=RegisterRepositoryService(repositories),
        indexing=indexing,
        lookup=ExactSymbolLookupService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            evidence=evidence,
        ),
        status=RepositoryStatusService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            jobs=jobs,
        ),
        recovery=recovery,
        entities=EntityService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            evidence=evidence,
        ),
        change_analysis=ChangeAnalysisService(
            repositories=repositories,
            snapshots=snapshots,
            analyses=analyses,
            indexing=indexing,
            git=GitAdapter(),
            diff=GitDiffAdapter(),
            connection=connection,
        ),
        graph=GraphQueryService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            relations=relations,
            evidence=evidence,
        ),
        search=LexicalSearchService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            symbols=symbols,
            search=search_store,
            evidence=evidence,
        ),
    )
