"""Bounded reranking primitives.

The production default is no reranker. These tests pin the parts that matter
before any provider is admitted: ordering remains stable without a provider,
and the cache key is a digest over truth-bearing dimensions rather than stored
source text.
"""

from __future__ import annotations

from codeatlas.semantic.reranking import (
    NoReranker,
    RerankCandidate,
    RerankRequest,
    rerank_cache_key,
)


def _request(*, query: str = "where is stock held?") -> RerankRequest:
    return RerankRequest(
        repository_id="repo_1",
        snapshot_id="snap_1",
        query=query,
        candidates=(
            RerankCandidate(
                candidate_id="ev_a",
                content_hash="hash_a",
                text="secret repository excerpt",
            ),
            RerankCandidate(
                candidate_id="ev_b",
                content_hash="hash_b",
                text="another excerpt",
            ),
        ),
    )


def test_no_reranker_preserves_candidate_order() -> None:
    request = _request()

    assert NoReranker().rerank(request) == ("ev_a", "ev_b")


def test_cache_key_is_a_digest_and_never_contains_candidate_text() -> None:
    key = rerank_cache_key(
        _request(), model_id="rerank-model", prompt_version="prompt-v1"
    )

    assert key.startswith("rerank_")
    assert "secret repository excerpt" not in key
    assert "where is stock held" not in key


def test_cache_key_changes_when_truth_bearing_inputs_change() -> None:
    base = rerank_cache_key(
        _request(), model_id="rerank-model", prompt_version="prompt-v1"
    )
    changed_query = rerank_cache_key(
        _request(query="where is inventory held?"),
        model_id="rerank-model",
        prompt_version="prompt-v1",
    )
    changed_model = rerank_cache_key(
        _request(), model_id="other-model", prompt_version="prompt-v1"
    )
    changed_prompt = rerank_cache_key(
        _request(), model_id="rerank-model", prompt_version="prompt-v2"
    )

    assert len({base, changed_query, changed_model, changed_prompt}) == 4

