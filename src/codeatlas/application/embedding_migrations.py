"""Shadow embedding namespace migration.

The migration record is repository-scoped; the vectors are namespace-scoped.
That split mirrors the rest of the semantic layer: SQLite records which
similarity space is active and which repository asked to move, while the vector
store remains derived data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from codeatlas.domain.errors import (
    EmbeddingMigrationNotFoundError,
    InvalidRequestError,
    ProviderDisabledError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
)
from codeatlas.domain.ids import embedding_migration_id, embedding_namespace_id
from codeatlas.domain.semantic import (
    EmbeddingMigration,
    EmbeddingMigrationStatus,
    EmbeddingNamespace,
    EmbeddingProviderKind,
    NamespaceStatus,
    ProviderPolicy,
)
from codeatlas.semantic.cache import EmbeddingCache, EmbeddingRequest
from codeatlas.semantic.membership import SnapshotMembershipFilter
from codeatlas.semantic.pipeline import SemanticCoverage, read_namespace_coverage
from codeatlas.semantic.providers import EmbeddingProvider, ProviderFactory
from codeatlas.semantic.vector_store import VectorStore
from codeatlas.storage.sqlite.connection import write_transaction
from codeatlas.storage.sqlite.semantic_stores import (
    EmbeddingMigrationStore,
    EmbeddingStore,
    NamespaceStore,
    ProviderPolicyStore,
)
from codeatlas.storage.sqlite.stores import RepositoryStore, SnapshotStore

MigrationTarget = Literal["target", "source"]


@dataclass(frozen=True)
class EmbeddingMigrationView:
    """The API-facing migration state."""

    migration_id: str
    repository_id: str
    status: str
    source_namespace_id: str
    target_namespace_id: str
    active_namespace_id: str | None
    snapshot_id: str | None
    source_coverage: float | None
    target_coverage: float | None
    target_total_count: int | None
    target_embedded_count: int | None
    target_pending_count: int | None
    target_failed_count: int | None
    target_model_id: str
    target_dimensions: int
    target_normalization_version: str
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    rolled_back_at: datetime | None


class EmbeddingMigrationService:
    """Create, backfill, cut over, and roll back embedding namespaces."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        vectors: VectorStore,
        build_provider: Callable[[ProviderPolicy], EmbeddingProvider] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection = connection
        self._repositories = RepositoryStore(connection)
        self._snapshots = SnapshotStore(connection)
        self._namespaces = NamespaceStore(connection)
        self._migrations = EmbeddingMigrationStore(connection)
        self._policies = ProviderPolicyStore(connection)
        self._embeddings = EmbeddingStore(connection)
        self._vectors = vectors
        self._build_provider = (
            build_provider
            if build_provider is not None
            else ProviderFactory(connection).build
        )
        self._now = now

    def start(self, repository_id: str) -> EmbeddingMigrationView:
        """Create or resume a shadow migration for the configured provider."""
        self._require_repository(repository_id)
        snapshot = self._snapshots.get_active(repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot to backfill."
            )

        policy = self._policies.get(repository_id)
        if policy.embedding_provider is EmbeddingProviderKind.NONE:
            raise ProviderDisabledError(
                "Enable an embedding provider before starting a model migration."
            )
        provider = self._build_provider(policy)

        source = self._namespaces.get_active()
        if source is None:
            raise InvalidRequestError(
                "There is no active embedding namespace to migrate from."
            )

        target = self._ensure_shadow_namespace(provider, source)
        if target.namespace_id == source.namespace_id:
            raise InvalidRequestError("The selected embedding model is already active.")

        moment = self._now()
        migration_id = embedding_migration_id(
            repository_id, source.namespace_id, target.namespace_id
        )
        migration = EmbeddingMigration(
            migration_id=migration_id,
            repository_id=repository_id,
            source_namespace_id=source.namespace_id,
            target_namespace_id=target.namespace_id,
            status=EmbeddingMigrationStatus.BACKFILLING,
            created_at=moment,
            updated_at=moment,
            activated_at=None,
            rolled_back_at=None,
            failure_code=None,
        )
        self._migrations.upsert(migration)

        target_coverage = self._backfill(snapshot.snapshot_id, target, provider)
        status = (
            EmbeddingMigrationStatus.READY_FOR_CUTOVER
            if target_coverage.is_complete
            else EmbeddingMigrationStatus.FAILED
        )
        self._migrations.set_status(
            migration_id,
            status=status,
            updated_at=self._now(),
            failure_code=None if target_coverage.is_complete else "BACKFILL_INCOMPLETE",
        )
        return self.get(migration_id)

    def get(self, migration_id: str) -> EmbeddingMigrationView:
        migration = self._migrations.get(migration_id)
        if migration is None:
            raise EmbeddingMigrationNotFoundError(
                "No embedding migration matches that ID."
            )
        return self._view(migration)

    def activate(
        self, migration_id: str, *, target: MigrationTarget = "target"
    ) -> EmbeddingMigrationView:
        """Activate the migration target, or the source for rollback."""
        migration = self._migrations.get(migration_id)
        if migration is None:
            raise EmbeddingMigrationNotFoundError(
                "No embedding migration matches that ID."
            )

        namespace_id = (
            migration.target_namespace_id
            if target == "target"
            else migration.source_namespace_id
        )
        namespace = self._namespaces.get(namespace_id)
        if namespace is None:
            raise EmbeddingMigrationNotFoundError(
                "The migration namespace is no longer available."
            )

        snapshot = self._snapshots.get_active(migration.repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot to validate."
            )
        if target == "target":
            coverage = read_namespace_coverage(
                self._connection, migration.target_namespace_id, snapshot.snapshot_id
            )
            if not coverage.is_complete:
                raise InvalidRequestError(
                    "The target namespace is not fully backfilled.",
                    details={
                        "migration_id": migration_id,
                        "target_namespace_id": migration.target_namespace_id,
                    },
                )

        moment = self._now()
        with write_transaction(self._connection):
            self._namespaces.activate(namespace_id, activated_at=moment)
            self._migrations.set_status(
                migration_id,
                status=(
                    EmbeddingMigrationStatus.ACTIVE
                    if target == "target"
                    else EmbeddingMigrationStatus.ROLLED_BACK
                ),
                updated_at=moment,
                activated_at=moment if target == "target" else None,
                rolled_back_at=moment if target == "source" else None,
                failure_code=None,
            )
        return self.get(migration_id)

    def _ensure_shadow_namespace(
        self, provider: EmbeddingProvider, source: EmbeddingNamespace
    ) -> EmbeddingNamespace:
        target_id = embedding_namespace_id(
            provider.model_id, provider.dimensions, provider.normalization_version
        )
        existing = self._namespaces.get(target_id)
        if existing is not None:
            if existing.status is NamespaceStatus.RETIRED:
                self._namespaces.set_status(target_id, NamespaceStatus.SHADOW)
                return self._namespaces.get(target_id) or existing
            return existing

        moment = self._now()
        target = EmbeddingNamespace(
            namespace_id=target_id,
            model_id=provider.model_id,
            dimensions=provider.dimensions,
            normalization_version=provider.normalization_version,
            status=NamespaceStatus.SHADOW,
            created_at=moment,
            activated_at=None,
        )
        self._namespaces.add(target)
        return target

    def _backfill(
        self,
        snapshot_id: str,
        namespace: EmbeddingNamespace,
        provider: EmbeddingProvider,
    ) -> SemanticCoverage:
        membership = SnapshotMembershipFilter(self._connection)
        all_hashes = membership.content_hashes_in_snapshot(snapshot_id)
        missing = self._embeddings.missing_content_hashes(
            namespace.namespace_id, content_hashes=all_hashes
        )
        texts = membership.retrieval_texts(snapshot_id, missing)
        cache = EmbeddingCache(
            provider=provider,
            store=self._embeddings,
            namespace=namespace,
            now=self._now,
        )
        cache.embed_missing(
            [
                EmbeddingRequest(content_hash=content_hash, text=texts[content_hash])
                for content_hash in missing
                if content_hash in texts
            ],
            persist=lambda records: self._vectors.upsert(
                namespace.namespace_id, records
            ),
        )
        return read_namespace_coverage(
            self._connection, namespace.namespace_id, snapshot_id
        )

    def _view(self, migration: EmbeddingMigration) -> EmbeddingMigrationView:
        active = self._namespaces.get_active()
        snapshot = self._snapshots.get_active(migration.repository_id)
        target_namespace = self._namespaces.get(migration.target_namespace_id)
        if target_namespace is None:
            raise EmbeddingMigrationNotFoundError(
                "The migration namespace is no longer available."
            )

        source_coverage: float | None = None
        target_coverage: SemanticCoverage | None = None
        if snapshot is not None:
            source_coverage = read_namespace_coverage(
                self._connection,
                migration.source_namespace_id,
                snapshot.snapshot_id,
            ).ratio
            target_coverage = read_namespace_coverage(
                self._connection,
                migration.target_namespace_id,
                snapshot.snapshot_id,
            )

        return EmbeddingMigrationView(
            migration_id=migration.migration_id,
            repository_id=migration.repository_id,
            status=migration.status.value,
            source_namespace_id=migration.source_namespace_id,
            target_namespace_id=migration.target_namespace_id,
            active_namespace_id=active.namespace_id if active else None,
            snapshot_id=snapshot.snapshot_id if snapshot else None,
            source_coverage=source_coverage,
            target_coverage=target_coverage.ratio if target_coverage else None,
            target_total_count=target_coverage.total if target_coverage else None,
            target_embedded_count=target_coverage.embedded if target_coverage else None,
            target_pending_count=target_coverage.pending if target_coverage else None,
            target_failed_count=target_coverage.failed if target_coverage else None,
            target_model_id=target_namespace.model_id,
            target_dimensions=target_namespace.dimensions,
            target_normalization_version=target_namespace.normalization_version,
            failure_code=migration.failure_code,
            created_at=migration.created_at,
            updated_at=migration.updated_at,
            activated_at=migration.activated_at,
            rolled_back_at=migration.rolled_back_at,
        )

    def _require_repository(self, repository_id: str) -> None:
        if self._repositories.get(repository_id) is None:
            raise RepositoryNotFoundError("The repository is not registered.")


__all__ = [
    "EmbeddingMigrationService",
    "EmbeddingMigrationView",
    "MigrationTarget",
]
