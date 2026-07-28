"""Application service wiring.

Every delivery adapter — CLI, REST, and anything added later — builds its
services here. That is what keeps repository logic in one place rather than
letting each adapter grow its own variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection

from codeatlas.application.change_analysis import ChangeAnalysisService
from codeatlas.application.conversation_service import ConversationService
from codeatlas.application.entities import EntityService
from codeatlas.application.graph_queries import GraphQueryService
from codeatlas.application.indexing import IndexRepositoryService
from codeatlas.application.lookup import ExactSymbolLookupService
from codeatlas.application.recovery import SnapshotRecoveryService
from codeatlas.application.registration import RegisterRepositoryService
from codeatlas.application.status import RepositoryStatusService
from codeatlas.conversations.events import EventHub
from codeatlas.conversations.executor import RunExecutor
from codeatlas.conversations.pipeline import AnswerPipeline
from codeatlas.parsing.registry import default_registry
from codeatlas.repositories.git_diff import GitDiffAdapter
from codeatlas.repositories.git_state import GitAdapter
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.retrieval.lexical import LexicalSearchService
from codeatlas.storage.sqlite.stores import (
    ChangeAnalysisStore,
    ChunkStore,
    ConversationStore,
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
    conversations: ConversationService
    # The repository store itself, for the few operations that are settings on a
    # repository rather than behavior over one — the watch switch is the first.
    # Wrapping a single boolean column in a service would add a layer that only
    # forwarded.
    repositories: RepositoryStore


def build_services(
    connection: Connection,
    *,
    hub: EventHub | None = None,
    executor: RunExecutor | None = None,
) -> ApplicationServices:
    """Construct the application services for one database connection.

    ``hub`` must be supplied by any adapter that serves more than one request
    against the same process. Services are built per request, so a hub created
    here would be a *different* hub for the request that starts a run and the
    request that streams it — the stream would find nothing. The API owns one
    hub for the application's lifetime and passes it in; a one-shot caller
    (the CLI, a test) can let this default and never notice.

    ``executor`` decides where an accepted turn is answered. Supplying one
    makes submission return as soon as the turn is committed (ADR-0008);
    leaving it out answers on the calling thread, which is what a one-shot
    caller wants and what keeps the pipeline directly testable.
    """
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
    conversations = ConversationStore(connection)

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

    # Hoisted because the conversation pipeline answers through these exact
    # services. Constructing a second set would let the chat surface and
    # `/v1/query` drift apart while both looked correct in isolation.
    lookup = ExactSymbolLookupService(
        repositories=repositories,
        snapshots=snapshots,
        files=files,
        symbols=symbols,
        evidence=evidence,
    )
    graph = GraphQueryService(
        repositories=repositories,
        snapshots=snapshots,
        files=files,
        symbols=symbols,
        relations=relations,
        evidence=evidence,
    )
    search = LexicalSearchService(
        repositories=repositories,
        snapshots=snapshots,
        files=files,
        symbols=symbols,
        search=search_store,
        evidence=evidence,
    )

    return ApplicationServices(
        repositories=repositories,
        registration=RegisterRepositoryService(repositories),
        indexing=indexing,
        lookup=lookup,
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
        conversations=ConversationService(
            repositories=repositories,
            conversations=conversations,
            connection=connection,
            # The pipeline is handed the same services every other adapter
            # uses. That is what makes the conversation answer and the
            # `/v1/query` answer the same answer rather than two that agree
            # by coincidence.
            pipeline=AnswerPipeline(lookup=lookup, graph=graph, search=search),
            hub=hub if hub is not None else EventHub(),
            executor=executor,
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
        graph=graph,
        search=search,
    )
