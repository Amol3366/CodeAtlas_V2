"""Application service wiring.

Every delivery adapter — CLI, REST, and anything added later — builds its
services here. That is what keeps repository logic in one place rather than
letting each adapter grow its own variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection

from codeatlas.application.answer_generation import RepositoryAnswerExplainer
from codeatlas.application.change_analysis import ChangeAnalysisService
from codeatlas.application.conversation_service import ConversationService
from codeatlas.application.credentials import CredentialService
from codeatlas.application.embedding_migrations import EmbeddingMigrationService
from codeatlas.application.entities import EntityService
from codeatlas.application.graph_queries import GraphQueryService
from codeatlas.application.indexing import (
    IndexRepositoryService,
    SnapshotEmbedding,
)
from codeatlas.application.lookup import ExactSymbolLookupService
from codeatlas.application.recovery import SnapshotRecoveryService
from codeatlas.application.registration import RegisterRepositoryService
from codeatlas.application.semantic_fusion import SemanticFusionService
from codeatlas.application.semantic_status import SemanticStatusService
from codeatlas.application.settings import SettingsService
from codeatlas.application.status import RepositoryStatusService
from codeatlas.conversations.events import EventHub
from codeatlas.conversations.executor import RunExecutor
from codeatlas.conversations.pipeline import (
    AnswerExplainer,
    AnswerPipeline,
    SemanticFusion,
)
from codeatlas.parsing.registry import default_registry
from codeatlas.repositories.git_diff import GitDiffAdapter
from codeatlas.repositories.git_state import GitAdapter
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.retrieval.lexical import LexicalSearchService
from codeatlas.retrieval.semantic import SemanticSearchService
from codeatlas.semantic.pipeline import SnapshotEmbedder
from codeatlas.semantic.vector_store import InMemoryVectorStore, VectorStore
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
    # Built here rather than injected like `embedding`, because it reads SQLite
    # and constructs no provider and no vector store: there is nothing optional
    # in it that could be missing. A repository with no provider gets an honest
    # "not applicable" from it, on every installation.
    semantic_status: SemanticStatusService
    # Built here for the same reason as `semantic_status`: it reads and
    # writes SQLite and constructs no provider until asked to test one.
    settings: SettingsService
    # Holds no connection: the credential lives in an OS store, not in SQLite,
    # so a backup and a support bundle cannot carry it.
    credentials: CredentialService
    # Same application boundary as the settings service: model changes create
    # and activate shadow namespaces, and all adapters must share that logic.
    embedding_migrations: EmbeddingMigrationService
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
    embedding: SnapshotEmbedding | None = None,
    fusion: SemanticFusion | None = None,
    explainer: AnswerExplainer | None = None,
    vectors: VectorStore | None = None,
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

    ``embedding`` attaches the optional semantic layer to indexing. Left out —
    the default, and what every installation that opted into nothing gets —
    indexing behaves exactly as it did in Phases 0-6. It is a parameter rather
    than something constructed here because this module must not import the
    semantic package: the deterministic path may not acquire a dependency on
    the layer that is allowed to be absent.

    ``fusion`` is the query-time half of the same arrangement, and is injected
    for the same reason: it needs a vector store, and choosing one is a
    deployment decision this module has no input for. Left out — the default —
    the answer pipeline is exactly the Phase 5 pipeline, and a test asserts that
    a question answered without it completes normally.
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
    vector_store = vectors or InMemoryVectorStore()
    semantic_status = SemanticStatusService(connection)
    settings = SettingsService(connection)
    credentials = CredentialService()

    if embedding is None and vectors is not None:
        embedding = SnapshotEmbedder(connection=connection, vectors=vector_store)

    recovery = SnapshotRecoveryService(
        repositories=repositories,
        snapshots=snapshots,
        search=search_store,
        jobs=jobs,
        connection=connection,
    )
    # Heal anything a crashed predecessor left mid-build before this process
    # serves a single query. The return value is deliberately dropped: what was
    # recovered is written onto the job it describes, because services are
    # built per request and the request that discovers a crash is almost never
    # the one asked about it later.
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
        # Retention is wired here rather than left to callers so the bound
        # holds for every adapter. Before P6-08 nothing called `prune` at all,
        # and every index left its predecessor behind permanently.
        retention=recovery,
        embedding=embedding,
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
        relations=relations,
        evidence=evidence,
    )
    if explainer is None:
        # Built unconditionally, unlike `fusion`. It constructs no provider
        # until a question arrives, and a repository whose policy says `none`
        # gets `NoAnswerProvider` — so there is nothing optional here that
        # could be missing, and no import of a package that may not be
        # installed.
        explainer = RepositoryAnswerExplainer(connection)

    if fusion is None and vectors is not None:
        fusion = SemanticFusionService(
            repositories=repositories,
            snapshots=snapshots,
            files=files,
            evidence=evidence,
            status=semantic_status,
            semantic=SemanticSearchService(
                connection=connection,
                vectors=vector_store,
            ),
        )

    return ApplicationServices(
        repositories=repositories,
        registration=RegisterRepositoryService(
            repositories=repositories,
            # Deletion has to know what it would take with it: the schema
            # cascades conversations from repositories, so the refusal lives
            # here rather than in the database.
            conversations=conversations,
            search=search_store,
            connection=connection,
        ),
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
            pipeline=AnswerPipeline(
                lookup=lookup,
                graph=graph,
                search=search,
                fusion=fusion,
                explainer=explainer,
            ),
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
        semantic_status=semantic_status,
        settings=settings,
        credentials=credentials,
        embedding_migrations=EmbeddingMigrationService(
            connection=connection,
            vectors=vector_store,
        ),
    )
