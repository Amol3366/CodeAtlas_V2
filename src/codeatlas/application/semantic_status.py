"""How much of a snapshot the semantic index covers, and under which model.

This is the product's fourth and fifth questions — how current is the evidence,
and what does CodeAtlas not know — asked of the one index that is permitted to
lag behind the snapshot it describes. Deterministic activation never waits for
embeddings (`AGENTS.md` Section 16), so "the snapshot is active" and "the
snapshot is fully embedded" are different facts, and a product that reported
only the first would be hiding the second.

The type keeps three states apart that a single float would merge:

* **not applicable** — no provider is enabled, so coverage is ``None``. A
  repository that opted into nothing is not partially indexed.
* **nothing yet** — opted in, no vectors written. Coverage is 0.0, which is the
  honest answer during the window between enabling a provider and the next
  index.
* **partial** — some content embedded, some pending or failed, counted
  separately because they need different remedies: pending resolves itself,
  failed needs someone told.

Unlike the embedder, this service constructs no provider and touches no vector
store. It reads SQLite, so it cannot fail because an optional dependency is
missing — which is why the composition root builds it directly rather than
injecting it the way it injects the embedder.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from codeatlas.domain.errors import RepositoryNotFoundError
from codeatlas.domain.semantic import EmbeddingProviderKind
from codeatlas.semantic.pipeline import read_coverage
from codeatlas.storage.sqlite.semantic_stores import NamespaceStore, ProviderPolicyStore
from codeatlas.storage.sqlite.stores import RepositoryStore, SnapshotStore


@dataclass(frozen=True)
class SemanticStatus:
    """One repository's semantic index, as it stands right now."""

    repository_id: str
    provider: EmbeddingProviderKind
    # Null before the first index, and for a repository whose snapshot was
    # never activated. Coverage without a snapshot ID is a number with no
    # referent, and a client could render it beside a newer snapshot.
    snapshot_id: str | None
    # All four are ``None`` when no provider is enabled — see the module
    # docstring on why that is not 0.
    coverage: float | None
    total_count: int | None
    embedded_count: int | None
    pending_count: int | None
    failed_count: int | None
    namespace_id: str | None
    model_id: str | None

    @property
    def enabled(self) -> bool:
        return self.provider is not EmbeddingProviderKind.NONE

    @property
    def is_complete(self) -> bool:
        """Whether every eligible chunk has a vector.

        ``True`` for a disabled repository: nothing was promised, so nothing is
        outstanding. A caller deciding whether to show a partial-coverage
        banner wants that to read as "no banner".
        """
        return self.coverage is None or self.coverage >= 1.0


class SemanticStatusService:
    """Report the semantic index state for one repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._repositories = RepositoryStore(connection)
        self._snapshots = SnapshotStore(connection)

    def status(self, repository_id: str) -> SemanticStatus:
        """Describe this repository's semantic coverage.

        Raises :class:`RepositoryNotFoundError` for an unknown repository, and
        nothing else. A repository that has never been indexed, or that opted
        into no provider, is an ordinary question with an ordinary answer.
        """
        if self._repositories.get(repository_id) is None:
            raise RepositoryNotFoundError("The repository is not registered.")

        policy = ProviderPolicyStore(self._connection).get(repository_id)
        snapshot = self._snapshots.get_active(repository_id)
        snapshot_id = snapshot.snapshot_id if snapshot is not None else None

        if policy.embedding_provider is EmbeddingProviderKind.NONE or snapshot is None:
            return SemanticStatus(
                repository_id=repository_id,
                provider=policy.embedding_provider,
                snapshot_id=snapshot_id,
                coverage=None,
                total_count=None,
                embedded_count=None,
                pending_count=None,
                failed_count=None,
                namespace_id=None,
                model_id=None,
            )

        coverage = read_coverage(self._connection, repository_id, snapshot.snapshot_id)
        namespace = NamespaceStore(self._connection).get_active()
        if coverage is None:
            # Only reachable if the policy changed between the two reads. The
            # disabled shape is the safe answer: it claims nothing.
            return SemanticStatus(
                repository_id=repository_id,
                provider=policy.embedding_provider,
                snapshot_id=snapshot_id,
                coverage=None,
                total_count=None,
                embedded_count=None,
                pending_count=None,
                failed_count=None,
                namespace_id=None,
                model_id=None,
            )

        return SemanticStatus(
            repository_id=repository_id,
            provider=policy.embedding_provider,
            snapshot_id=snapshot_id,
            coverage=coverage.ratio,
            total_count=coverage.total,
            embedded_count=coverage.embedded,
            pending_count=coverage.pending,
            failed_count=coverage.failed,
            namespace_id=namespace.namespace_id if namespace else None,
            model_id=namespace.model_id if namespace else None,
        )


__all__ = ["SemanticStatus", "SemanticStatusService"]
