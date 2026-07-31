"""Vector storage behind a narrow interface.

ADR-0009 decision 3: LanceDB is admitted, but only as derived, rebuildable data
behind an interface. Two consequences shape everything here.

**A vector row carries an embedding key, a content hash, and a vector — nothing
else.** Blueprint 4.7.4 lists richer metadata, and storing it would be a second
copy of the repository living outside the database that governs it. File paths
and line ranges come from SQLite at query time, where they are already bound to
a snapshot. Deleting the vectors directory therefore loses nothing but time.

**Base and delta are separate.** A normal edit appends a handful of vectors to a
small delta rather than rewriting a large base (blueprint 4.7.5). Compaction
folds delta into base and must be invisible to retrieval; it is a storage
decision, and a storage decision that changed answers would be a defect.

Scores are compared only *within* a namespace, which is the one place they are
comparable: same model, same dimensions, same normalization. Cross-namespace
comparison is blueprint 4.7.6's named error and cannot be expressed by this
interface.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from codeatlas.domain.errors import ProviderUnavailableError
from codeatlas.domain.ids import validate_namespace_id


@dataclass(frozen=True)
class VectorRecord:
    """One vector, with the two identifiers needed to use it again."""

    embedding_key: str
    content_hash: str
    vector: list[float]


@dataclass(frozen=True)
class VectorMatch:
    """A similarity hit. Not evidence — a candidate, until membership says so."""

    embedding_key: str
    content_hash: str
    score: float


class VectorStore(Protocol):
    """Write vectors, search them, and forget a whole namespace at once."""

    def upsert(self, namespace_id: str, records: Sequence[VectorRecord]) -> None: ...

    def search(
        self, namespace_id: str, query_vector: Sequence[float], *, limit: int
    ) -> tuple[VectorMatch, ...]: ...

    def compact(self, namespace_id: str) -> None: ...

    def delete_namespace(self, namespace_id: str) -> None: ...

    def count(self, namespace_id: str) -> int: ...


class InMemoryVectorStore:
    """A real implementation, used where LanceDB is not installed.

    Not a test double. The deterministic suite and the evaluation harness run
    against it, so it has to mean exactly what the LanceDB adapter means —
    `tests/semantic/test_lancedb_store.py` holds both to the same behaviours.

    It is also the honest choice for small repositories: an exact scan over a
    few thousand unit vectors is fast, and it has no index to be stale.
    """

    def __init__(self) -> None:
        self._base: dict[str, dict[str, VectorRecord]] = {}
        self._delta: dict[str, dict[str, VectorRecord]] = {}

    def upsert(self, namespace_id: str, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        validate_namespace_id(namespace_id)
        delta = self._delta.setdefault(namespace_id, {})
        width = self._width(namespace_id)
        for record in records:
            if width is not None and len(record.vector) != width:
                raise ValueError(
                    "vector width does not match the namespace: "
                    f"{len(record.vector)} != {width}"
                )
            width = len(record.vector)
            delta[record.embedding_key] = record

    def search(
        self, namespace_id: str, query_vector: Sequence[float], *, limit: int
    ) -> tuple[VectorMatch, ...]:
        width = self._width(namespace_id)
        if width is None:
            # Nothing written yet. An installation that enabled a provider but
            # has not indexed asks this on its first query; it is an ordinary
            # empty result, not a failure.
            return ()
        if len(query_vector) != width:
            raise ValueError(
                f"query width does not match the namespace: "
                f"{len(query_vector)} != {width}"
            )

        # Delta wins on a key collision: it holds the newer vector for content
        # that was re-embedded while the old one still sits in base. Returning
        # both would spend two of the caller's result slots on one chunk, one
        # of them stale.
        merged = dict(self._base.get(namespace_id, {}))
        merged.update(self._delta.get(namespace_id, {}))

        scored = [
            VectorMatch(
                embedding_key=record.embedding_key,
                content_hash=record.content_hash,
                score=_cosine(query_vector, record.vector),
            )
            for record in merged.values()
        ]
        # The key breaks ties deterministically. Two identical scores resolved
        # by dict order would make a ranking depend on insertion history, and
        # an evaluation run would stop being reproducible.
        scored.sort(key=lambda match: (-match.score, match.embedding_key))
        return tuple(scored[:limit])

    def compact(self, namespace_id: str) -> None:
        base = self._base.setdefault(namespace_id, {})
        base.update(self._delta.pop(namespace_id, {}))

    def delete_namespace(self, namespace_id: str) -> None:
        self._base.pop(namespace_id, None)
        self._delta.pop(namespace_id, None)

    def count(self, namespace_id: str) -> int:
        keys = set(self._base.get(namespace_id, {}))
        keys.update(self._delta.get(namespace_id, {}))
        return len(keys)

    def base_count(self, namespace_id: str) -> int:
        return len(self._base.get(namespace_id, {}))

    def delta_count(self, namespace_id: str) -> int:
        return len(self._delta.get(namespace_id, {}))

    def _width(self, namespace_id: str) -> int | None:
        for source in (self._delta, self._base):
            records = source.get(namespace_id)
            if records:
                return len(next(iter(records.values())).vector)
        return None


class LazyVectorStore:
    """Open the durable vector store only when semantic work actually runs.

    The API process should be able to start, register repositories, and answer
    deterministic queries on a machine without semantic extras installed. The
    first vector operation is the point where the optional dependency becomes
    required, so construction stays cheap and dependency-free.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._store: VectorStore | None = None

    def upsert(self, namespace_id: str, records: Sequence[VectorRecord]) -> None:
        self._inner().upsert(namespace_id, records)

    def search(
        self, namespace_id: str, query_vector: Sequence[float], *, limit: int
    ) -> tuple[VectorMatch, ...]:
        return self._inner().search(namespace_id, query_vector, limit=limit)

    def compact(self, namespace_id: str) -> None:
        self._inner().compact(namespace_id)

    def delete_namespace(self, namespace_id: str) -> None:
        self._inner().delete_namespace(namespace_id)

    def count(self, namespace_id: str) -> int:
        return self._inner().count(namespace_id)

    def _inner(self) -> VectorStore:
        if self._store is None:
            self._store = build_lancedb_store(self._directory)
        return self._store


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity.

    Vectors are normalized at write time, so this is usually a dot product.
    The magnitudes are divided out anyway: a provider whose normalization
    silently changed would otherwise produce scores that looked fine and ranked
    wrongly.
    """
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_magnitude = math.sqrt(sum(value * value for value in left))
    right_magnitude = math.sqrt(sum(value * value for value in right))
    if left_magnitude == 0.0 or right_magnitude == 0.0:
        return 0.0
    return dot / (left_magnitude * right_magnitude)


def build_lancedb_store(directory: object) -> VectorStore:
    """Open a LanceDB-backed store, or say what is missing.

    Lazily imported like every other optional dependency: importing this module
    must stay free on an installation that never opted in.
    """
    from pathlib import Path

    # The guard has to wrap *construction*, not just this import.
    # `lancedb_store` imports nothing optional at module scope — `import
    # lancedb` lives inside `LanceDBVectorStore.__init__`. Wrapping only the
    # module import therefore never fired, and a bare `ModuleNotFoundError`
    # escaped to a caller that had asked a question this function exists to
    # answer. In the embed path that surfaced as every content hash marked
    # `failed` with `VECTOR_WRITE_FAILED`, so coverage reported permanent
    # failure where it should have reported a missing extra.
    try:
        from codeatlas.semantic.lancedb_store import LanceDBVectorStore

        return LanceDBVectorStore(Path(str(directory)))
    except ImportError as error:
        raise ProviderUnavailableError(
            "Vector storage needs the 'semantic-local' or 'semantic-openai' "
            "extra. Install one with: uv sync --extra semantic-local",
        ) from error
