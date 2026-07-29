"""The content-hash embedding cache.

One job: decide what actually has to be embedded, and make sure the answer is
"only what changed". Blueprint 8.21 names the failure this prevents — a normal
edit triggering repository-wide re-embedding — and blueprint 15.2's steady-state
contract is what this implements: hash, compare, reuse, queue only the missing.

Two behaviours here look defensive and are not optional:

**A disabled provider is a quiet no-op.** Every default installation runs this
code on every index. If it raised, the indexing pipeline would need a try/except
around a path that is *supposed* to do nothing.

**A provider failure is recorded, not raised.** Gate condition 5 requires a
failing provider to degrade to a useful deterministic result. An exception
escaping here would fail the snapshot, which is the opposite.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from codeatlas.domain.ids import embedding_key
from codeatlas.domain.semantic import (
    EmbeddingNamespace,
    EmbeddingRecord,
    EmbeddingStatus,
)
from codeatlas.semantic.providers import EmbeddingProvider
from codeatlas.semantic.vector_store import VectorRecord
from codeatlas.storage.sqlite.semantic_stores import EmbeddingStore


@dataclass(frozen=True)
class EmbeddingRequest:
    """One piece of retrieval text and the hash that identifies it.

    The hash is the chunk's ``content_hash``, computed by the chunker. It is
    passed in rather than derived here so that one definition of "the same
    content" serves chunk reuse and embedding reuse alike — two definitions
    would drift, and the drift would show up as unexplained re-embedding.
    """

    content_hash: str
    text: str


@dataclass(frozen=True)
class EmbeddingBatch:
    """What one pass over a snapshot's chunks produced."""

    # Vectors for content embedded in *this* pass, ready for the vector store.
    # Reused content is deliberately absent: its vector is already stored, and
    # returning it would mean reading vectors back to write them again.
    vectors: dict[str, list[float]] = field(default_factory=dict)
    reused: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    # content hash -> embedding key, so a caller can find the record it wrote.
    keys: dict[str, str] = field(default_factory=dict)
    skipped_because_disabled: bool = False


class EmbeddingCache:
    """Embed what is missing, and nothing else."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        store: EmbeddingStore,
        namespace: EmbeddingNamespace,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch_size: int = 64,
    ) -> None:
        # A provider whose width disagrees with its namespace would write
        # incomparable vectors into one similarity space. Checked at
        # construction so the mismatch surfaces at wiring time rather than
        # mid-index, and so no partial batch is written before it is noticed.
        if provider.dimensions and provider.dimensions != namespace.dimensions:
            raise ValueError(
                "provider dimensions do not match the namespace: "
                f"{provider.dimensions} != {namespace.dimensions}"
            )
        self._provider = provider
        self._store = store
        self._namespace = namespace
        self._now = now
        self._batch_size = batch_size

    @property
    def is_enabled(self) -> bool:
        """Whether this cache would call a provider at all.

        ``dimensions == 0`` is `NoEmbeddingProvider`'s signature and cannot be
        reached by a real provider, since a namespace with no width cannot
        exist.
        """
        return self._provider.dimensions > 0

    def embed_missing(
        self,
        requests: Sequence[EmbeddingRequest],
        *,
        persist: Callable[[Sequence[VectorRecord]], None] | None = None,
    ) -> EmbeddingBatch:
        """Embed the content that has no vector yet in this namespace.

        ``persist`` is called with each window's vectors *before* they are
        marked embedded, so that ``embedded`` can only ever mean "a vector for
        this content exists". Without that ordering a failed vector write would
        leave a record claiming coverage it does not have, and the next run
        would skip the content — a permanent, silent gap.
        """
        if not self.is_enabled:
            # No rows are written. A `pending` row for a repository that will
            # never embed would report coverage that can never reach 1.0, and
            # a coverage figure nobody can satisfy is worse than none.
            return EmbeddingBatch(skipped_because_disabled=True)

        unique = self._deduplicate(requests)
        if not unique:
            return EmbeddingBatch()

        missing = set(
            self._store.missing_content_hashes(
                self._namespace.namespace_id, content_hashes=unique.keys()
            )
        )
        reused = tuple(sorted(hash_ for hash_ in unique if hash_ not in missing))
        keys = {
            content_hash: self._key(content_hash) for content_hash in unique
        }

        vectors: dict[str, list[float]] = {}
        failed: list[str] = []
        pending = [hash_ for hash_ in unique if hash_ in missing]

        for start in range(0, len(pending), self._batch_size):
            window = pending[start : start + self._batch_size]
            self._record_pending(window, keys)
            self._embed_window(window, unique, keys, vectors, failed, persist)

        return EmbeddingBatch(
            vectors=vectors,
            reused=reused,
            failed=tuple(sorted(failed)),
            keys=keys,
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed one query. Never cached in this table.

        The embedding cache is keyed by repository content hashes; a query is
        neither, and storing user questions is exactly what Section 4.4 says
        not to do.
        """
        vectors = self._provider.embed_queries([text])
        return vectors[0]

    def _deduplicate(
        self, requests: Sequence[EmbeddingRequest]
    ) -> dict[str, str]:
        """Collapse requests to one text per content hash, order preserved.

        Two files with identical content share a hash and therefore an
        embedding — a vendored copy or a generated stub should cost one call,
        not one per occurrence.
        """
        unique: dict[str, str] = {}
        for request in requests:
            unique.setdefault(request.content_hash, request.text)
        return unique

    def _key(self, content_hash: str) -> str:
        return embedding_key(
            content_hash,
            self._namespace.model_id,
            self._namespace.dimensions,
            self._namespace.normalization_version,
        )

    def _record_pending(self, window: list[str], keys: dict[str, str]) -> None:
        """Claim the work before doing it.

        Written first so that a process killed mid-batch leaves `pending` rows
        rather than nothing: the next run sees them as missing coverage and
        retries, instead of the work vanishing with the process.
        """
        moment = self._now()
        for content_hash in window:
            self._store.upsert(
                EmbeddingRecord(
                    embedding_key=keys[content_hash],
                    namespace_id=self._namespace.namespace_id,
                    content_hash=content_hash,
                    status=EmbeddingStatus.PENDING,
                    created_at=moment,
                    embedded_at=None,
                    failure_code=None,
                )
            )

    def _embed_window(
        self,
        window: list[str],
        unique: dict[str, str],
        keys: dict[str, str],
        vectors: dict[str, list[float]],
        failed: list[str],
        persist: Callable[[Sequence[VectorRecord]], None] | None = None,
    ) -> None:
        texts = [unique[content_hash] for content_hash in window]
        try:
            produced = self._provider.embed_documents(texts)
        except Exception:
            # Deliberately broad. A provider is third-party code — a socket
            # timeout, a tokenizer assertion, a CUDA error — and every one of
            # them means the same thing here: this content has no vector yet.
            # The alternative is an unlisted exception type failing a snapshot.
            for content_hash in window:
                self._store.mark_failed(
                    keys[content_hash], failure_code="PROVIDER_FAILED"
                )
                failed.append(content_hash)
            return

        if len(produced) != len(window):
            # A provider returning the wrong count cannot be zipped safely:
            # the vectors would be assigned to the wrong content, silently.
            for content_hash in window:
                self._store.mark_failed(
                    keys[content_hash], failure_code="PROVIDER_COUNT_MISMATCH"
                )
                failed.append(content_hash)
            return

        window_vectors = {
            content_hash: list(vector)
            for content_hash, vector in zip(window, produced, strict=True)
        }

        if persist is not None:
            try:
                persist(
                    [
                        VectorRecord(
                            embedding_key=keys[content_hash],
                            content_hash=content_hash,
                            vector=vector,
                        )
                        for content_hash, vector in window_vectors.items()
                    ]
                )
            except Exception:
                # The provider worked; storing the result did not. Recording
                # `embedded` here would claim coverage for content that has no
                # vector, and the next run would skip it — a gap that never
                # closes and never announces itself.
                for content_hash in window:
                    self._store.mark_failed(
                        keys[content_hash], failure_code="VECTOR_WRITE_FAILED"
                    )
                    failed.append(content_hash)
                return

        moment = self._now()
        for content_hash, vector in window_vectors.items():
            vectors[content_hash] = vector
            self._store.mark_embedded(keys[content_hash], embedded_at=moment)
