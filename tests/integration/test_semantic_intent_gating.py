"""Which questions the semantic channel is allowed to touch.

`AGENTS.md` Section 10.2 assigns each intent its channels, and the semantic
layer appears in exactly one of them: the conceptual question. Every other
intent is a *resolution* — an exact symbol, a call edge, a diff — and blueprint
15.6 rejects letting a similarity score participate in those. A resolved answer
that gained a semantic candidate would be offering a guess alongside a fact,
with no way for the reader to tell which mattered.

Gating is therefore tested as a prohibition, not as a preference: the provider
must not be *called at all* for a deterministic intent. Filtering its results
afterwards would still have spent the time and, for a transmitting provider,
still have sent the question.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.semantic_fusion import SemanticFusionService
from codeatlas.application.semantic_status import SemanticStatusService
from codeatlas.contracts import Derivation
from codeatlas.conversations.pipeline import AnswerPipeline, AnswerRequest
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.retrieval.semantic import SemanticSearchService
from codeatlas.semantic.pipeline import SnapshotEmbedder
from codeatlas.semantic.vector_store import InMemoryVectorStore
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore
from codeatlas.storage.sqlite.stores import (
    EvidenceStore,
    FileStore,
    RepositoryStore,
    SnapshotStore,
)

_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


class CountingProvider:
    """Records every query it is asked to embed."""

    model_id = "fake"
    dimensions = 2
    normalization_version = "l2_v1"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def _vector(self, text: str) -> list[float]:
        return [1.0, 0.0] if "capture" in text.lower() else [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.queries.extend(texts)
        return [self._vector(text) for text in texts]


class Fixture(NamedTuple):
    pipeline: AnswerPipeline
    bare_pipeline: AnswerPipeline
    provider: CountingProvider
    repository_id: str


@pytest.fixture()
def fixture(tmp_path: Path, sample_repo: Path) -> Iterator[Fixture]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        built.indexing.index(repository.repository_id)

        ProviderPolicyStore(connection).set(
            ProviderPolicy(
                repository_id=repository.repository_id,
                embedding_provider=EmbeddingProviderKind.LOCAL,
                monthly_token_budget=None,
                per_run_token_budget=None,
                updated_at=_NOW,
            )
        )
        provider = CountingProvider()
        vectors = InMemoryVectorStore()
        snapshots = SnapshotStore(connection)
        active = snapshots.get_active(repository.repository_id)
        assert active is not None
        SnapshotEmbedder(
            connection=connection,
            vectors=vectors,
            build_provider=lambda policy: provider,
            now=lambda: _NOW,
        ).embed_snapshot(repository.repository_id, active.snapshot_id)
        provider.queries.clear()

        fusion = SemanticFusionService(
            repositories=RepositoryStore(connection),
            snapshots=snapshots,
            files=FileStore(connection),
            evidence=EvidenceStore(connection),
            status=SemanticStatusService(connection),
            semantic=SemanticSearchService(
                connection=connection,
                vectors=vectors,
                build_provider=lambda policy: provider,
            ),
        )
        yield Fixture(
            pipeline=AnswerPipeline(
                lookup=built.lookup,
                graph=built.graph,
                search=built.search,
                fusion=fusion,
            ),
            bare_pipeline=AnswerPipeline(
                lookup=built.lookup, graph=built.graph, search=built.search
            ),
            provider=provider,
            repository_id=repository.repository_id,
        )


def _ask(pipeline: AnswerPipeline, repository_id: str, question: str):  # type: ignore[no-untyped-def]
    return pipeline.execute(
        AnswerRequest(
            repository_id=repository_id, question=question, request_id="req_1"
        )
    )


# --- the one intent the channel serves -----------------------------------


def test_a_conceptual_question_reaches_the_semantic_channel(
    fixture: Fixture,
) -> None:
    result = _ask(
        fixture.pipeline, fixture.repository_id, "how is a payment captured here"
    )

    assert fixture.provider.queries == ["how is a payment captured here"]
    assert any(
        item.derivation is Derivation.SEMANTIC_CANDIDATE
        for item in result.response.evidence
    )


# --- the intents it must not touch ---------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "PaymentService.capture",
        "who calls capture",
        "callees of capture",
        "dependencies of capture",
        "tests for capture",
        "docs for capture",
        "trace capture",
        "what changed",
    ],
)
def test_a_resolved_intent_never_reaches_the_provider(
    fixture: Fixture, question: str
) -> None:
    """Not merely "produces no semantic evidence" — the provider is never
    called. A transmitting provider would already have sent the question by the
    time results were filtered."""
    result = _ask(fixture.pipeline, fixture.repository_id, question)

    assert fixture.provider.queries == []
    assert all(
        item.derivation is not Derivation.SEMANTIC_CANDIDATE
        for item in result.response.evidence
    )


# --- the composition seam ------------------------------------------------


def test_the_container_can_be_given_a_fusion_layer(
    tmp_path: Path, sample_repo: Path
) -> None:
    """`build_services` must be able to *accept* the layer, the way it already
    accepts the embedder. Without this parameter the channel is reachable only
    by a test constructing `AnswerPipeline` by hand, which is not a product."""
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        built.indexing.index(repository.repository_id)

        ProviderPolicyStore(connection).set(
            ProviderPolicy(
                repository_id=repository.repository_id,
                embedding_provider=EmbeddingProviderKind.LOCAL,
                monthly_token_budget=None,
                per_run_token_budget=None,
                updated_at=_NOW,
            )
        )
        provider = CountingProvider()
        vectors = InMemoryVectorStore()
        snapshots = SnapshotStore(connection)
        active = snapshots.get_active(repository.repository_id)
        assert active is not None
        SnapshotEmbedder(
            connection=connection,
            vectors=vectors,
            build_provider=lambda policy: provider,
            now=lambda: _NOW,
        ).embed_snapshot(repository.repository_id, active.snapshot_id)

        wired = build_services(
            connection,
            fusion=SemanticFusionService(
                repositories=RepositoryStore(connection),
                snapshots=snapshots,
                files=FileStore(connection),
                evidence=EvidenceStore(connection),
                status=SemanticStatusService(connection),
                semantic=SemanticSearchService(
                    connection=connection,
                    vectors=vectors,
                    build_provider=lambda policy: provider,
                ),
            ),
        )
        conversation = wired.conversations.create(repository.repository_id)
        result = wired.conversations.submit(
            conversation.conversation_id, "how is a payment captured here"
        )

        assert result.status.value == "complete"
        assert "how is a payment captured here" in provider.queries


def test_the_container_leaves_the_layer_out_by_default(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Every installation that opted into nothing gets Phases 0-6 exactly."""
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        built.indexing.index(repository.repository_id)
        conversation = built.conversations.create(repository.repository_id)

        result = built.conversations.submit(
            conversation.conversation_id, "how is a payment captured here"
        )

        assert result.status.value == "complete"


# --- the layer stays removable -------------------------------------------


def test_a_pipeline_without_the_layer_answers_a_conceptual_question_identically(
    fixture: Fixture,
) -> None:
    """The deterministic half of a fused answer must equal the whole answer a
    pipeline without the layer produces."""
    question = "how is a payment captured here"

    fused = _ask(fixture.pipeline, fixture.repository_id, question).response
    bare = _ask(fixture.bare_pipeline, fixture.repository_id, question).response

    assert fused.evidence[: len(bare.evidence)] == bare.evidence
    assert fused.answer.claims[: len(bare.answer.claims)] == bare.answer.claims
    assert fused.answer.summary == bare.answer.summary
