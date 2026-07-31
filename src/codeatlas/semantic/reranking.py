"""Optional bounded reranking over semantic candidates.

Reranking is a presentation of candidate order, not a new authority. The
default implementation preserves order, and any real provider must be injected
explicitly after evaluation admits it.

The cache stores only a digest key and ordered candidate IDs. Candidate text is
present in the request because a reranker needs something to score, but it is
never written into the key or cache value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from codeatlas.domain.ids import stable_hash

MAX_RERANK_CANDIDATES = 8
RERANK_POLICY_VERSION = "phase7-rerank-v1"
NO_RERANK_MODEL_ID = "none"
NO_RERANK_PROMPT_VERSION = "none"


@dataclass(frozen=True)
class RerankCandidate:
    """One verified semantic candidate offered to a reranker."""

    candidate_id: str
    content_hash: str
    text: str


@dataclass(frozen=True)
class RerankRequest:
    """One bounded, structured reranking request."""

    repository_id: str
    snapshot_id: str
    query: str
    candidates: Sequence[RerankCandidate]
    policy_version: str = RERANK_POLICY_VERSION


class Reranker(Protocol):
    """A provider-neutral reranker.

    A result is an ordered list of candidate IDs from the supplied request. A
    caller treats unknown or duplicate IDs as a provider failure and keeps the
    original order.
    """

    model_id: str
    prompt_version: str

    def rerank(self, request: RerankRequest) -> tuple[str, ...]: ...


class NoReranker:
    """The safe default: preserve input order and perform no provider work."""

    model_id = NO_RERANK_MODEL_ID
    prompt_version = NO_RERANK_PROMPT_VERSION

    def rerank(self, request: RerankRequest) -> tuple[str, ...]:
        return tuple(candidate.candidate_id for candidate in request.candidates)


class RerankCache:
    """Digest-keyed cache for candidate ordering.

    In-memory by design for P7-10. The cache is an optimization within one
    process and stores no source text; a restart recomputes rather than reading
    a stale persistent ordering.
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, ...]] = {}

    def get(self, key: str) -> tuple[str, ...] | None:
        return self._items.get(key)

    def put(self, key: str, ordered_ids: Sequence[str]) -> None:
        self._items[key] = tuple(ordered_ids)


def rerank_cache_key(
    request: RerankRequest, *, model_id: str, prompt_version: str
) -> str:
    """Digest every truth-bearing input without storing source text."""
    candidate_digest = stable_hash(
        *(
            f"{candidate.candidate_id}:"
            f"{candidate.content_hash}:"
            f"{position}"
            for position, candidate in enumerate(request.candidates)
        )
    )
    return "rerank_" + stable_hash(
        request.repository_id,
        request.snapshot_id,
        _normalize_query(request.query),
        candidate_digest,
        request.policy_version,
        model_id,
        prompt_version,
    )


def _normalize_query(query: str) -> str:
    return " ".join(query.split()).casefold()


__all__ = [
    "MAX_RERANK_CANDIDATES",
    "RERANK_POLICY_VERSION",
    "NoReranker",
    "RerankCache",
    "RerankCandidate",
    "RerankRequest",
    "Reranker",
    "rerank_cache_key",
]

