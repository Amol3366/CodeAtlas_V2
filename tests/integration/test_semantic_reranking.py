"""Optional reranking over semantic candidates.

Reranking is deliberately narrower than fusion: it may reorder semantic
candidates, but it must not reorder deterministic evidence or turn a model
judgment into a stronger derivation.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple, cast

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.semantic_fusion import SemanticFusionService
from codeatlas.application.semantic_status import SemanticStatusService
from codeatlas.contracts import QueryResponse
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.retrieval.semantic import SemanticSearchResult
from codeatlas.semantic.membership import SemanticCandidate
from codeatlas.semantic.reranking import RerankCache, RerankRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import (
    ChunkStore,
    EvidenceStore,
    FileStore,
    RepositoryStore,
    SnapshotStore,
)


class StaticSemanticSearch:
    def __init__(self, candidates: tuple[SemanticCandidate, ...]) -> None:
        self._candidates = candidates

    def search(self, request: object) -> SemanticSearchResult:
        return SemanticSearchResult(candidates=self._candidates, enabled=True)


class RecordingReranker:
    model_id = "fake-reranker"
    prompt_version = "prompt-v1"

    def __init__(self) -> None:
        self.calls: list[RerankRequest] = []

    def rerank(self, request: RerankRequest) -> tuple[str, ...]:
        self.calls.append(request)
        return tuple(
            reversed([candidate.candidate_id for candidate in request.candidates])
        )


class ExplodingReranker(RecordingReranker):
    def rerank(self, request: RerankRequest) -> tuple[str, ...]:
        self.calls.append(request)
        raise TimeoutError("reranker unavailable")


class Fixture(NamedTuple):
    connection: object
    services: object
    repository_id: str
    snapshot_id: str
    candidates: tuple[SemanticCandidate, ...]


@pytest.fixture()
def fixture(tmp_path: Path, sample_repo: Path) -> Iterator[Fixture]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        active = SnapshotStore(connection).get_active(repository.repository_id)
        assert active is not None
        chunks = ChunkStore(connection).list_for_snapshot(active.snapshot_id)
        seen: set[tuple[str, int, int]] = set()
        candidates: list[SemanticCandidate] = []
        for chunk in chunks:
            region = (chunk.file_id, chunk.start_line, chunk.end_line)
            if region in seen:
                continue
            seen.add(region)
            candidates.append(
                SemanticCandidate(
                    logical_chunk_id=chunk.logical_chunk_id,
                    chunk_version_id=chunk.chunk_version_id,
                    snapshot_id=active.snapshot_id,
                    file_id=chunk.file_id,
                    content_hash=chunk.content_hash,
                    qualified_name=chunk.qualified_name,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    part_index=chunk.part_index,
                    score=1.0 - (len(candidates) / 10),
                )
            )
            if len(candidates) == 3:
                break
        assert len(candidates) == 3
        yield Fixture(
            connection=connection,
            services=services,
            repository_id=repository.repository_id,
            snapshot_id=active.snapshot_id,
            candidates=tuple(candidates),
        )


def _fusion(
    fixture: Fixture,
    *,
    reranker: object | None,
    cache: RerankCache | None = None,
    max_candidates: int = 2,
) -> SemanticFusionService:
    connection = fixture.connection
    snapshots = SnapshotStore(connection)  # type: ignore[arg-type]
    return SemanticFusionService(
        repositories=RepositoryStore(connection),  # type: ignore[arg-type]
        snapshots=snapshots,
        files=FileStore(connection),  # type: ignore[arg-type]
        evidence=EvidenceStore(connection),  # type: ignore[arg-type]
        status=SemanticStatusService(connection),  # type: ignore[arg-type]
        semantic=StaticSemanticSearch(fixture.candidates),  # type: ignore[arg-type]
        reranker=reranker,  # type: ignore[arg-type]
        rerank_cache=cache,
        max_rerank_candidates=max_candidates,
    )


def _empty_base(fixture: Fixture) -> QueryResponse:
    return cast(
        QueryResponse,
        fixture.services.search.search_text(  # type: ignore[attr-defined]
            SearchRequest(
                repository_id=fixture.repository_id,
                query="zzzz_no_match",
                request_id="req_1",
            )
        )
    )


def test_reranking_is_bounded_and_uses_one_structured_call(
    fixture: Fixture,
) -> None:
    reranker = RecordingReranker()

    response = _fusion(fixture, reranker=reranker).augment(
        _empty_base(fixture), question="where should I look first?"
    )

    assert len(reranker.calls) == 1
    assert len(reranker.calls[0].candidates) == 2
    assert [item.evidence_id for item in response.evidence[:2]] == list(
        reversed([candidate.candidate_id for candidate in reranker.calls[0].candidates])
    )


def test_rerank_cache_reuses_the_digest_key(fixture: Fixture) -> None:
    cache = RerankCache()
    reranker = RecordingReranker()
    fusion = _fusion(fixture, reranker=reranker, cache=cache)
    base = _empty_base(fixture)

    first = fusion.augment(base, question="where should I look first?")
    second = fusion.augment(base, question="where should I look first?")

    assert len(reranker.calls) == 1
    assert second.evidence == first.evidence


def test_reranking_does_not_move_deterministic_evidence(
    fixture: Fixture,
) -> None:
    base = fixture.services.search.search_text(  # type: ignore[attr-defined]
        SearchRequest(
            repository_id=fixture.repository_id,
            query="capture",
            request_id="req_1",
        )
    )
    assert base.evidence

    response = _fusion(fixture, reranker=RecordingReranker()).augment(
        base, question="where should I look first?"
    )

    assert response.evidence[: len(base.evidence)] == base.evidence
    assert response.answer.claims[: len(base.answer.claims)] == base.answer.claims


def test_reranker_failure_preserves_the_semantic_result(
    fixture: Fixture,
) -> None:
    base = _empty_base(fixture)
    without_rerank = _fusion(fixture, reranker=None).augment(
        base, question="where should I look first?"
    )

    response = _fusion(fixture, reranker=ExplodingReranker()).augment(
        base, question="where should I look first?"
    )

    assert response.evidence == without_rerank.evidence
    assert "RERANK_FAILED" in response.warnings
