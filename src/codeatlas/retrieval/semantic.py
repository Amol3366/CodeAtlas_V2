"""The semantic retrieval channel.

A discovery channel, never an authority. `AGENTS.md` Section 4.3 draws the line
this module lives on: a model score may widen what CodeAtlas *finds*, and may
never promote what it finds to evidence. Everything returned here is a
`SemanticCandidate` and stays labelled `semantic_candidate` until independent
deterministic or static evidence supports the same claim.

**This service cannot fail its caller.** Every path returns a result; none
raises. The caller has already computed a deterministic answer by the time this
runs, and a provider timeout that propagated would throw away a good answer to
report a failure in an optional layer. So a missing extra, a dead model, a
vanished vector directory, and a repository that never opted in all produce the
same shape: no candidates, a named warning where one is useful, and no
exception.

Eligibility comes from SQLite, not from the vector store. See
`semantic/membership.py` — the vector store may physically hold anything, and
the join against the snapshot's chunks is what decides which of it a query is
allowed to see.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.semantic.membership import SemanticCandidate, SnapshotMembershipFilter
from codeatlas.semantic.providers import EmbeddingProvider, ProviderFactory
from codeatlas.semantic.vector_store import VectorStore
from codeatlas.storage.sqlite.semantic_stores import NamespaceStore, ProviderPolicyStore

# Bounded per Section 10.3. Deliberately smaller than the lexical bound: these
# are candidates fused alongside a deterministic answer, and a channel that can
# contribute more items than the answer it supplements has stopped supplementing
# it.
MAX_SEMANTIC_CANDIDATES = 10

# Codes, not messages. A message can quote the payload that caused it, and
# payloads are repository content (Section 4.4).
PROVIDER_UNAVAILABLE_WARNING = "SEMANTIC_PROVIDER_UNAVAILABLE"
PROVIDER_FAILED_WARNING = "SEMANTIC_PROVIDER_FAILED"
INDEX_UNAVAILABLE_WARNING = "SEMANTIC_INDEX_UNAVAILABLE"


@dataclass(frozen=True)
class SemanticSearchRequest:
    """A bounded semantic search over one already-resolved snapshot.

    The snapshot is an input rather than something resolved here, and that is
    deliberate: the caller has already answered from a specific snapshot, and
    re-resolving could hand back candidates from a newer one that the
    deterministic half of the answer never saw.
    """

    repository_id: str
    snapshot_id: str
    query: str
    limit: int = MAX_SEMANTIC_CANDIDATES


@dataclass(frozen=True)
class SemanticSearchResult:
    """What the channel found, and what it could not do."""

    candidates: tuple[SemanticCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
    # Whether a provider is enabled at all. Distinguishes "opted in and found
    # nothing" from "never opted in" — the second is not a degraded state and
    # must not be reported as one.
    enabled: bool = False
    namespace_id: str | None = None
    timing_ms: dict[str, float] = field(default_factory=dict)


class SemanticSearchService:
    """Find snapshot-resident chunks whose content is near a query."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        vectors: VectorStore,
        build_provider: Callable[[ProviderPolicy], EmbeddingProvider] | None = None,
    ) -> None:
        self._connection = connection
        self._vectors = vectors
        # See SnapshotEmbedder: the factory is the governed route, so it is
        # the default rather than something a caller has to remember.
        self._build_provider = (
            build_provider
            if build_provider is not None
            else ProviderFactory(connection).build
        )

    def search(self, request: SemanticSearchRequest) -> SemanticSearchResult:
        """Return candidates for this query, or say why there are none."""
        policy = ProviderPolicyStore(self._connection).get(request.repository_id)
        if policy.embedding_provider is EmbeddingProviderKind.NONE:
            # No warning. This is the default on every installation, and a
            # warning that appears on every answer teaches the reader to ignore
            # warnings.
            return SemanticSearchResult()

        query = request.query.strip()
        if not query:
            return SemanticSearchResult(enabled=True)

        # The provider is checked before the index, and the order is a decision
        # rather than an accident. A repository whose extra was never installed
        # has no index *because* it has no provider; reporting the missing index
        # would send someone to reindex when the fix is to install the extra.
        # Cause beats symptom.
        try:
            provider = self._build_provider(policy)
        except Exception:
            return SemanticSearchResult(
                enabled=True, warnings=(PROVIDER_UNAVAILABLE_WARNING,)
            )

        namespace = NamespaceStore(self._connection).get_active()
        if namespace is None:
            # Opted in, nothing embedded yet. Every repository looks like this
            # between switching the provider on and the next index.
            return SemanticSearchResult(
                enabled=True, warnings=(INDEX_UNAVAILABLE_WARNING,)
            )

        started = time.perf_counter()
        try:
            vectors = provider.embed_queries([query])
        except Exception:
            # Timeout, killed model process, out-of-memory. Broad on purpose:
            # the set of ways a provider can fail is not ours to enumerate, and
            # an unanticipated one must degrade exactly like an anticipated one.
            return SemanticSearchResult(
                enabled=True,
                namespace_id=namespace.namespace_id,
                warnings=(PROVIDER_FAILED_WARNING,),
            )
        embed_ms = (time.perf_counter() - started) * 1000

        if not vectors or not vectors[0]:
            return SemanticSearchResult(
                enabled=True,
                namespace_id=namespace.namespace_id,
                warnings=(PROVIDER_FAILED_WARNING,),
            )

        started = time.perf_counter()
        try:
            matches = self._vectors.search(
                namespace.namespace_id, vectors[0], limit=max(1, request.limit)
            )
        except Exception:
            # A deleted vectors directory, a width mismatch left by a
            # half-finished model change. The vectors are derived and
            # rebuildable, so this is a degraded channel rather than a broken
            # repository.
            return SemanticSearchResult(
                enabled=True,
                namespace_id=namespace.namespace_id,
                warnings=(INDEX_UNAVAILABLE_WARNING,),
            )
        search_ms = (time.perf_counter() - started) * 1000

        candidates = SnapshotMembershipFilter(self._connection).keep_active(
            request.snapshot_id, matches
        )
        return SemanticSearchResult(
            candidates=candidates[: max(1, request.limit)],
            enabled=True,
            namespace_id=namespace.namespace_id,
            timing_ms={"semantic_embed": embed_ms, "semantic_search": search_ms},
        )


__all__ = [
    "INDEX_UNAVAILABLE_WARNING",
    "MAX_SEMANTIC_CANDIDATES",
    "PROVIDER_FAILED_WARNING",
    "PROVIDER_UNAVAILABLE_WARNING",
    "SemanticSearchRequest",
    "SemanticSearchResult",
    "SemanticSearchService",
]
