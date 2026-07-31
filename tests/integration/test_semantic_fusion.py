"""Fusing semantic candidates into a deterministic answer.

The property under test throughout is subtraction-proof: removing the semantic
layer must leave the deterministic answer byte-identical. That is what makes it
an *optional* recall layer rather than a component the answer depends on, and it
is the only form of "deterministic fallback" that can actually be verified —
asserting that a fallback "works" proves nothing if the fallback path is a
different answer.

So most tests here take the same question twice, once with the layer and once
without, and compare.
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
from codeatlas.contracts import Derivation, QueryResponse, SnapshotFreshness
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.retrieval.lexical import SearchRequest
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


class KeywordProvider:
    """Points along axis 0 when the text mentions the keyword, else axis 1.

    Fake, but it produces real similarity structure over the real chunk texts
    the indexer wrote, so ranking is genuinely exercised rather than stubbed.
    """

    model_id = "fake"
    dimensions = 2
    normalization_version = "l2_v1"

    def __init__(self, keyword: str = "capture") -> None:
        self._keyword = keyword
        self.calls = 0

    def _vector(self, text: str) -> list[float]:
        return [1.0, 0.0] if self._keyword in text.lower() else [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(text) for text in texts]


class BrokenProvider(KeywordProvider):
    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        raise TimeoutError("the model did not answer")


class Fixture(NamedTuple):
    connection: object
    repository_id: str
    deterministic: QueryResponse
    vectors: InMemoryVectorStore


@pytest.fixture()
def fixture(tmp_path: Path, sample_repo: Path) -> Iterator[Fixture]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        built.indexing.index(repository.repository_id)
        deterministic = built.search.search_text(
            SearchRequest(
                repository_id=repository.repository_id,
                query="capture",
                request_id="req_1",
            )
        )
        yield Fixture(
            connection, repository.repository_id, deterministic, InMemoryVectorStore()
        )


def _opt_in(fixture: Fixture) -> None:
    ProviderPolicyStore(fixture.connection).set(  # type: ignore[arg-type]
        ProviderPolicy(
            repository_id=fixture.repository_id,
            embedding_provider=EmbeddingProviderKind.LOCAL,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )


def _embed(fixture: Fixture, provider: object) -> None:
    SnapshotEmbedder(
        connection=fixture.connection,  # type: ignore[arg-type]
        vectors=fixture.vectors,
        build_provider=lambda policy: provider,  # type: ignore[arg-type,return-value]
        now=lambda: _NOW,
    ).embed_snapshot(fixture.repository_id, fixture.deterministic.snapshot.snapshot_id)


def _fusion(fixture: Fixture, provider: object) -> SemanticFusionService:
    connection = fixture.connection
    return SemanticFusionService(
        repositories=RepositoryStore(connection),  # type: ignore[arg-type]
        snapshots=SnapshotStore(connection),  # type: ignore[arg-type]
        files=FileStore(connection),  # type: ignore[arg-type]
        evidence=EvidenceStore(connection),  # type: ignore[arg-type]
        status=SemanticStatusService(connection),  # type: ignore[arg-type]
        semantic=SemanticSearchService(
            connection=connection,  # type: ignore[arg-type]
            vectors=fixture.vectors,
            build_provider=lambda policy: provider,  # type: ignore[arg-type,return-value]
        ),
    )


# --- the layer must be removable ----------------------------------------


def test_a_disabled_repository_gets_back_the_identical_response(
    fixture: Fixture,
) -> None:
    """Gate condition 5, in its strongest form. Not "an answer is still
    produced" — the *same* answer, field for field."""
    provider = KeywordProvider()

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert augmented == fixture.deterministic
    assert provider.calls == 0


def test_a_failing_provider_leaves_the_deterministic_claims_untouched(
    fixture: Fixture,
) -> None:
    _opt_in(fixture)
    _embed(fixture, KeywordProvider())

    augmented = _fusion(fixture, BrokenProvider()).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert augmented.answer.claims == fixture.deterministic.answer.claims
    assert augmented.evidence == fixture.deterministic.evidence
    assert "SEMANTIC_PROVIDER_FAILED" in augmented.warnings


def test_a_provider_failure_is_reported_rather_than_swallowed(
    fixture: Fixture,
) -> None:
    """Section 4.1: say what CodeAtlas does not know. A silently degraded
    channel looks exactly like a channel that found nothing."""
    _opt_in(fixture)
    _embed(fixture, KeywordProvider())

    augmented = _fusion(fixture, BrokenProvider()).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert augmented.warnings != fixture.deterministic.warnings


# --- candidates are additions, never promotions --------------------------


def test_semantic_evidence_is_labelled_a_candidate(fixture: Fixture) -> None:
    """Section 11: a model score may not promote anything to deterministic
    evidence. The derivation is the label that keeps that visible downstream."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    added = augmented.evidence[len(fixture.deterministic.evidence) :]
    assert added
    assert all(item.derivation is Derivation.SEMANTIC_CANDIDATE for item in added)


def test_deterministic_evidence_keeps_its_place_and_its_derivation(
    fixture: Fixture,
) -> None:
    """Appended, not merged. A semantic hit that reordered the deterministic
    answer would be deciding relevance, which is the authority it does not
    have."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    prefix = augmented.evidence[: len(fixture.deterministic.evidence)]
    assert prefix == fixture.deterministic.evidence


def test_semantic_claims_are_labelled_and_cite_their_evidence(
    fixture: Fixture,
) -> None:
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    added = augmented.answer.claims[len(fixture.deterministic.answer.claims) :]
    assert added
    evidence_ids = {item.evidence_id for item in augmented.evidence}
    for claim in added:
        assert claim.derivation is Derivation.SEMANTIC_CANDIDATE
        assert claim.evidence_ids
        assert set(claim.evidence_ids) <= evidence_ids


def test_a_region_already_cited_is_not_cited_a_second_time(
    fixture: Fixture,
) -> None:
    """The lexical channel and the semantic channel find the same chunk often —
    that is the point of fusing them. Citing it twice would mislead a reader
    into thinking two independent sources agreed."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    regions = [
        (item.file_path, item.start_line, item.end_line) for item in augmented.evidence
    ]
    assert len(regions) == len(set(regions))


def test_every_semantic_claim_id_is_unique(fixture: Fixture) -> None:
    """Claim IDs are referenced by citations. A collision with a deterministic
    claim would silently repoint a citation at the wrong claim."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    ids = [claim.claim_id for claim in augmented.answer.claims]
    assert len(ids) == len(set(ids))


def test_semantic_evidence_is_bound_to_the_answering_snapshot(
    fixture: Fixture,
) -> None:
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    snapshot_id = fixture.deterministic.snapshot.snapshot_id
    assert all(item.snapshot_id == snapshot_id for item in augmented.evidence)


# --- coverage reaches the envelope ---------------------------------------


def test_the_envelope_reports_real_coverage_once_the_layer_is_on(
    fixture: Fixture,
) -> None:
    """`semantic_coverage` was hardcoded 0.0 from Phase 0 until here. A field
    that always reads 0.0 is worse than absent: it looks like a measurement."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert fixture.deterministic.snapshot.semantic_coverage == 0.0
    assert augmented.snapshot.semantic_coverage == pytest.approx(1.0)


def test_incomplete_coverage_is_reported_as_partial_freshness(
    fixture: Fixture,
) -> None:
    """`SnapshotFreshness.PARTIAL` has existed unused since Phase 0 for exactly
    this state: the deterministic snapshot is current, the semantic index is
    still catching up, and the user is entitled to know."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)
    _add_unembedded_chunk(fixture)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert augmented.snapshot.semantic_coverage < 1.0
    assert augmented.snapshot.freshness is SnapshotFreshness.PARTIAL


def test_a_disabled_repository_keeps_the_freshness_it_had(
    fixture: Fixture,
) -> None:
    """No provider means nothing was promised, so nothing is outstanding.
    Marking these snapshots partial would put a coverage banner on every
    deterministic-only installation."""
    augmented = _fusion(fixture, KeywordProvider()).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert augmented.snapshot.freshness is fixture.deterministic.snapshot.freshness


def _add_unembedded_chunk(fixture: Fixture) -> None:
    """Put content in the snapshot that no vector covers."""
    connection = fixture.connection
    row = connection.execute(  # type: ignore[attr-defined]
        "SELECT file_id FROM files WHERE snapshot_id = ? LIMIT 1",
        (fixture.deterministic.snapshot.snapshot_id,),
    ).fetchone()
    connection.execute(  # type: ignore[attr-defined]
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES (?, 'chunk_new', 'chunkv_new', ?, NULL, 'symbol', 'new', '',"
        " 1, 2, 'hash_never_embedded', 'never embedded', 0, 1)",
        (fixture.deterministic.snapshot.snapshot_id, row[0]),
    )


def test_the_limitation_of_semantic_discovery_is_stated(fixture: Fixture) -> None:
    """Section 4.1 again. A candidate that looked like a finding would be a
    stronger claim than the evidence supports."""
    _opt_in(fixture)
    provider = KeywordProvider()
    _embed(fixture, provider)

    augmented = _fusion(fixture, provider).augment(
        fixture.deterministic, question="how does capture work"
    )

    assert any("semantic" in text.lower() for text in augmented.limitations)
