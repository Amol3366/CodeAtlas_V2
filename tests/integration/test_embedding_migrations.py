"""Shadow embedding migration lifecycle.

P7-09 exists to make model changes explicit and reversible. The active
namespace keeps serving while a shadow namespace fills; cutover is one SQLite
transaction; the previous namespace is retained so rollback can reactivate it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.application.embedding_migrations import EmbeddingMigrationService
from codeatlas.domain.ids import embedding_key, embedding_namespace_id
from codeatlas.domain.semantic import (
    EmbeddingNamespace,
    EmbeddingProviderKind,
    EmbeddingRecord,
    EmbeddingStatus,
    NamespaceStatus,
    ProviderPolicy,
)
from codeatlas.semantic.vector_store import InMemoryVectorStore
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import (
    EmbeddingMigrationStore,
    EmbeddingStore,
    NamespaceStore,
    ProviderPolicyStore,
)

_NOW = datetime(2026, 7, 30, 18, 0, 0, tzinfo=UTC)


class FakeProvider:
    model_id = "target-model"
    dimensions = 3
    normalization_version = "l2_v1"

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


@pytest.fixture()
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-30T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO snapshots ("
            " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
            " working_tree_fingerprint, file_count, parsed_file_count,"
            " skipped_file_count, parse_error_count, parser_bundle_version,"
            " index_version, created_at, activated_at"
            ") VALUES ('snap_1', 'repo_1', 'active', NULL, NULL, 0, 'fp', 1, 1, 0,"
            " 0, '1.0.0', '1.0.0', '2026-07-30T00:00:00Z',"
            " '2026-07-30T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO files ("
            " snapshot_id, file_id, relative_path, display_path, content_hash,"
            " size_bytes, line_count, language, classification"
            ") VALUES ('snap_1', 'file_1', 'a.py', 'a.py', 'fh', 1, 10,"
            " 'python', 'source_code')"
        )
        yield conn


def _chunk(connection: sqlite3.Connection, name: str, content_hash: str) -> None:
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES ('snap_1', ?, ?, 'file_1', NULL, 'symbol', ?, '', 1, 5, ?, ?,"
        " 0, 1)",
        (name, f"chunkv_{content_hash}", name, content_hash, f"text {content_hash}"),
    )


def _active_namespace(connection: sqlite3.Connection) -> EmbeddingNamespace:
    namespace = EmbeddingNamespace(
        namespace_id=embedding_namespace_id("source-model", 3, "l2_v1"),
        model_id="source-model",
        dimensions=3,
        normalization_version="l2_v1",
        status=NamespaceStatus.ACTIVE,
        created_at=_NOW,
        activated_at=_NOW,
    )
    NamespaceStore(connection).add(namespace)
    return namespace


def _mark_source_covered(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace, content_hash: str
) -> None:
    EmbeddingStore(connection).upsert(
        EmbeddingRecord(
            embedding_key=embedding_key(
                content_hash,
                namespace.model_id,
                namespace.dimensions,
                namespace.normalization_version,
            ),
            namespace_id=namespace.namespace_id,
            content_hash=content_hash,
            status=EmbeddingStatus.EMBEDDED,
            created_at=_NOW,
            embedded_at=_NOW,
            failure_code=None,
        )
    )


def _opt_in(connection: sqlite3.Connection) -> None:
    ProviderPolicyStore(connection).set(
        ProviderPolicy(
            repository_id="repo_1",
            embedding_provider=EmbeddingProviderKind.LOCAL,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )


def _service(
    connection: sqlite3.Connection,
    provider: FakeProvider,
    vectors: InMemoryVectorStore | None = None,
) -> EmbeddingMigrationService:
    return EmbeddingMigrationService(
        connection=connection,
        vectors=vectors or InMemoryVectorStore(),
        build_provider=lambda policy: provider,
        now=lambda: _NOW,
    )


def test_start_backfills_a_shadow_namespace_without_moving_active(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _chunk(connection, "chunk_b", "hash_b")
    source = _active_namespace(connection)
    _mark_source_covered(connection, source, "hash_a")
    _mark_source_covered(connection, source, "hash_b")
    _opt_in(connection)
    provider = FakeProvider()
    vectors = InMemoryVectorStore()

    migration = _service(connection, provider, vectors).start("repo_1")

    target = NamespaceStore(connection).get(migration.target_namespace_id)
    assert target is not None
    assert target.status is NamespaceStatus.SHADOW
    assert NamespaceStore(connection).get_active() == source
    assert sorted(provider.embedded) == ["text hash_a", "text hash_b"]
    assert vectors.count(migration.target_namespace_id) == 2
    assert migration.status == "ready_for_cutover"
    assert migration.source_coverage == pytest.approx(1.0)
    assert migration.target_coverage == pytest.approx(1.0)


def test_cutover_is_atomic_and_retains_the_previous_namespace_for_rollback(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    source = _active_namespace(connection)
    _mark_source_covered(connection, source, "hash_a")
    _opt_in(connection)
    provider = FakeProvider()
    service = _service(connection, provider)
    migration = service.start("repo_1")

    activated = service.activate(migration.migration_id, target="target")

    namespaces = NamespaceStore(connection)
    assert namespaces.get_active() is not None
    assert namespaces.get_active().namespace_id == migration.target_namespace_id  # type: ignore[union-attr]
    assert namespaces.get(source.namespace_id).status is NamespaceStatus.RETIRED  # type: ignore[union-attr]
    assert activated.status == "active"

    rolled_back = service.activate(migration.migration_id, target="source")

    assert namespaces.get_active() is not None
    assert namespaces.get_active().namespace_id == source.namespace_id  # type: ignore[union-attr]
    assert (
        namespaces.get(migration.target_namespace_id).status  # type: ignore[union-attr]
        is NamespaceStatus.RETIRED
    )
    assert rolled_back.status == "rolled_back"


def test_get_reports_the_persisted_migration_record(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    source = _active_namespace(connection)
    _mark_source_covered(connection, source, "hash_a")
    _opt_in(connection)
    migration = _service(connection, FakeProvider()).start("repo_1")

    restored = _service(connection, FakeProvider()).get(migration.migration_id)

    assert restored.migration_id == migration.migration_id
    assert restored.repository_id == "repo_1"
    assert restored.source_namespace_id == source.namespace_id
    assert restored.target_namespace_id == migration.target_namespace_id


def test_migration_rows_cascade_with_the_repository(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _active_namespace(connection)
    _opt_in(connection)
    migration = _service(connection, FakeProvider()).start("repo_1")

    connection.execute("DELETE FROM repositories WHERE repository_id = 'repo_1'")

    assert EmbeddingMigrationStore(connection).get(migration.migration_id) is None
