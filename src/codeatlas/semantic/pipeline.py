"""Embedding a snapshot, and reporting how much of it is covered.

The ordering is the whole design. A snapshot is validated and activated by the
deterministic pipeline, and only then does anything here run. AGENTS.md
Section 4.2 requires exact, lexical, graph, and Git retrieval to stay available
while semantic indexing is incomplete or unavailable, and the cheapest way to
guarantee that is for the semantic work to be structurally unable to affect
activation: it happens afterwards, against a snapshot that is already answering
queries, and every failure it can produce is a warning.

Coverage is computed, never stored. A column would be one more thing that can
disagree with the truth, and "how current is that evidence?" is the product's
third question — the one answer that must not be approximate.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from codeatlas.domain.errors import CodeAtlasError
from codeatlas.domain.ids import embedding_namespace_id
from codeatlas.domain.semantic import (
    EmbeddingNamespace,
    EmbeddingProviderKind,
    EmbeddingStatus,
    NamespaceStatus,
    ProviderPolicy,
)
from codeatlas.semantic.cache import EmbeddingCache, EmbeddingRequest
from codeatlas.semantic.membership import SnapshotMembershipFilter
from codeatlas.semantic.providers import EmbeddingProvider, ProviderFactory
from codeatlas.semantic.vector_store import VectorStore
from codeatlas.storage.sqlite.semantic_stores import (
    EmbeddingStore,
    NamespaceStore,
    ProviderPolicyStore,
)

# Warning codes, not messages. They cross into `IndexResult.warnings`, which is
# a published surface, and a message would eventually carry a path or a model
# error into a log that Section 4.4 says holds neither.
PROVIDER_UNAVAILABLE_WARNING = "SEMANTIC_PROVIDER_UNAVAILABLE"
EMBEDDING_INCOMPLETE_WARNING = "SEMANTIC_EMBEDDING_INCOMPLETE"


@dataclass(frozen=True)
class EmbeddingRunResult:
    """What one embedding pass over one snapshot did."""

    namespace_id: str | None = None
    embedded: int = 0
    reused: int = 0
    failed: int = 0
    # ``None`` when no provider is enabled. Distinct from 0.0, which would read
    # as "we looked and found nothing embedded" — a repository that opted into
    # nothing is not missing coverage, the question does not apply to it.
    coverage: float | None = None
    skipped_because_disabled: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class SemanticCoverage:
    """How much of a snapshot's content has a vector."""

    total: int
    embedded: int
    pending: int
    failed: int

    @property
    def ratio(self) -> float:
        """Fraction covered, where an empty snapshot is complete.

        Nothing to embed is fully embedded. Reporting 0.0 would raise a partial
        freshness banner over a repository that has nothing in it.
        """
        if self.total == 0:
            return 1.0
        return self.embedded / self.total

    @property
    def is_complete(self) -> bool:
        return self.embedded == self.total


class SnapshotEmbedder:
    """Embed the chunks of an already-active snapshot."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        vectors: VectorStore,
        build_provider: Callable[[ProviderPolicy], EmbeddingProvider] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection = connection
        self._vectors = vectors
        # Defaults to the factory rather than the bare builder, because the
        # factory is what wraps a transmitting provider in redaction,
        # budgets, and telemetry. A default that skipped it would make the
        # governed path opt-in, which is exactly backwards.
        self._build_provider = (
            build_provider
            if build_provider is not None
            else ProviderFactory(connection).build
        )
        self._now = now

    def embed_snapshot(
        self, repository_id: str, snapshot_id: str
    ) -> EmbeddingRunResult:
        """Bring one snapshot's semantic coverage up to date.

        Returns rather than raises, in every path. The caller is the indexing
        service, which has already activated the snapshot by the time this
        runs; an exception here would turn a good deterministic index into a
        failed one.
        """
        policy = ProviderPolicyStore(self._connection).get(repository_id)
        if policy.embedding_provider is EmbeddingProviderKind.NONE:
            # No namespace is created and no rows are written. A `pending` row
            # for a repository that will never embed would report coverage
            # that could never reach 1.0.
            return EmbeddingRunResult(skipped_because_disabled=True)

        try:
            provider = self._build_provider(policy)
        except CodeAtlasError:
            # The usual cause is a setting switched on before the extra was
            # installed. Deterministic retrieval is unaffected, so this is
            # something to report, not something to fail.
            return EmbeddingRunResult(warning=PROVIDER_UNAVAILABLE_WARNING)

        namespace = self._ensure_namespace(provider, repository_id)
        membership = SnapshotMembershipFilter(self._connection)
        embeddings = EmbeddingStore(self._connection)

        all_hashes = membership.content_hashes_in_snapshot(snapshot_id)
        missing = embeddings.missing_content_hashes(
            namespace.namespace_id, content_hashes=all_hashes
        )
        texts = membership.retrieval_texts(snapshot_id, missing)

        cache = EmbeddingCache(
            provider=provider,
            store=embeddings,
            namespace=namespace,
            now=self._now,
        )
        batch = cache.embed_missing(
            [
                EmbeddingRequest(content_hash=content_hash, text=texts[content_hash])
                for content_hash in missing
                if content_hash in texts
            ],
            # The vector write happens inside the cache so that `embedded` can
            # only mean "a vector exists". See EmbeddingCache.embed_missing.
            persist=lambda records: self._vectors.upsert(
                namespace.namespace_id, records
            ),
        )

        coverage = read_coverage(self._connection, repository_id, snapshot_id)
        return EmbeddingRunResult(
            namespace_id=namespace.namespace_id,
            embedded=len(batch.vectors),
            reused=len(all_hashes) - len(missing),
            failed=len(batch.failed),
            coverage=coverage.ratio if coverage is not None else None,
            warning=EMBEDDING_INCOMPLETE_WARNING if batch.failed else None,
        )

    def _ensure_namespace(
        self, provider: EmbeddingProvider, repository_id: str
    ) -> EmbeddingNamespace:
        """Find or create the namespace this provider writes into, and point
        this repository at it.

        Derived from the provider's own identity rather than from
        configuration: a namespace has to describe the vectors actually in it,
        and a configured name could outlive the model it was chosen for.

        The namespace is shared — two repositories on the same model use the
        same one, which is what makes the content-hash cache reusable across
        repositories. The *pointer* is per repository, because the provider
        setting is (ADR-0009 decision 5, ADR-0010). Before migration `0012`
        this method marked any second namespace `shadow`, since a global
        one-active index left no alternative; the effect was that the second
        repository to opt in embedded into a space nothing ever queried.
        """
        namespaces = NamespaceStore(self._connection)
        namespace_id = embedding_namespace_id(
            provider.model_id, provider.dimensions, provider.normalization_version
        )
        moment = self._now()
        existing = namespaces.get(namespace_id)
        if existing is None:
            existing = EmbeddingNamespace(
                namespace_id=namespace_id,
                model_id=provider.model_id,
                dimensions=provider.dimensions,
                normalization_version=provider.normalization_version,
                status=NamespaceStatus.ACTIVE,
                created_at=moment,
                activated_at=moment,
            )
            namespaces.add(existing)

        # Re-asserted every run, so a provider switch retargets the repository
        # on its next index rather than needing a separate step.
        namespaces.set_for_repository(
            repository_id, existing.namespace_id, updated_at=moment
        )
        return existing


def read_coverage(
    connection: sqlite3.Connection, repository_id: str, snapshot_id: str
) -> SemanticCoverage | None:
    """How much of this snapshot has a vector, or ``None`` if none was asked for.

    Computed from the snapshot's chunks joined against the embedding cache, so
    it cannot drift from what is actually stored. ``None`` for a repository
    with no provider keeps "not applicable" distinguishable from "nothing
    covered".
    """
    policy = ProviderPolicyStore(connection).get(repository_id)
    if policy.embedding_provider is EmbeddingProviderKind.NONE:
        return None

    hashes = SnapshotMembershipFilter(connection).content_hashes_in_snapshot(
        snapshot_id
    )
    total = len(hashes)

    # The repository's own namespace, not whichever one happens to be
    # active: with two repositories on different providers the global
    # lookup computed each one's coverage against the other's space.
    namespace = NamespaceStore(connection).get_for_repository(repository_id)
    if namespace is None or total == 0:
        # Opted in, but nothing embedded yet — the first index after switching
        # a provider on looks exactly like this. Reporting `None` would say the
        # question does not apply, when the honest answer is "none of it is
        # covered". An empty snapshot lands here too, and `ratio` reads it as
        # complete, because nothing to embed is fully embedded.
        return SemanticCoverage(total=total, embedded=0, pending=0, failed=0)

    return read_namespace_coverage(connection, namespace.namespace_id, snapshot_id)


def read_namespace_coverage(
    connection: sqlite3.Connection, namespace_id: str, snapshot_id: str
) -> SemanticCoverage:
    """How much of ``snapshot_id`` is covered in one namespace.

    Used by model migrations to evaluate source and target namespaces
    independently. The function does not compare scores or rankings across
    namespaces; it counts membership and embedding states only.
    """
    hashes = SnapshotMembershipFilter(connection).content_hashes_in_snapshot(
        snapshot_id
    )
    total = len(hashes)
    if total == 0:
        return SemanticCoverage(total=0, embedded=0, pending=0, failed=0)

    counts = {status: 0 for status in EmbeddingStatus}
    placeholders = ", ".join("?" for _ in hashes)
    rows = connection.execute(
        "SELECT status, COUNT(DISTINCT content_hash) FROM embeddings"
        f" WHERE namespace_id = ? AND content_hash IN ({placeholders})"
        " GROUP BY status",
        (namespace_id, *hashes),
    ).fetchall()
    for row in rows:
        counts[EmbeddingStatus(row[0])] = int(row[1])

    return SemanticCoverage(
        total=total,
        embedded=counts[EmbeddingStatus.EMBEDDED],
        pending=counts[EmbeddingStatus.PENDING],
        failed=counts[EmbeddingStatus.FAILED],
    )
