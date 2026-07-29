"""Embedding a snapshot, after it is already active.

The ordering is the design. Deterministic activation happens first and does not
wait; embedding runs afterwards against a snapshot that is already answering
queries. AGENTS.md Section 4.2 requires exact, lexical, graph, and Git retrieval
to stay available while semantic indexing is incomplete, and the cheapest way to
guarantee that is for the semantic work to be unable to affect activation at
all.

So the tests here are mostly about what *cannot* happen: a missing provider
cannot fail an index, a dying process cannot lose work silently, and a
repository that opted into nothing cannot be given a coverage figure it could
never reach.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.errors import ProviderUnavailableError
from codeatlas.domain.semantic import (
    EmbeddingProviderKind,
    EmbeddingStatus,
    ProviderPolicy,
)
from codeatlas.semantic.pipeline import SnapshotEmbedder, read_coverage
from codeatlas.semantic.vector_store import InMemoryVectorStore
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import (
    EmbeddingStore,
    NamespaceStore,
    ProviderPolicyStore,
)

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


class FakeProvider:
    model_id = "fake"
    dimensions = 3
    normalization_version = "l2_v1"

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class ExplodingProvider(FakeProvider):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise TimeoutError("provider gone")


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-29T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO snapshots ("
            " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
            " working_tree_fingerprint, file_count, parsed_file_count,"
            " skipped_file_count, parse_error_count, parser_bundle_version,"
            " index_version, created_at, activated_at"
            ") VALUES ('snap_1', 'repo_1', 'active', NULL, NULL, 0, 'fp', 1, 1, 0,"
            " 0, '1.0.0', '1.0.0', '2026-07-29T00:00:00Z', '2026-07-29T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO files ("
            " snapshot_id, file_id, relative_path, display_path, content_hash,"
            " size_bytes, line_count, language, classification"
            ") VALUES ('snap_1', 'file_1', 'a.py', 'a.py', 'fh', 1, 10, 'python',"
            " 'source_code')"
        )
        yield conn


def _chunk(connection: sqlite3.Connection, chunk_id: str, content_hash: str) -> None:
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES ('snap_1', ?, ?, 'file_1', NULL, 'symbol', ?, '', 1, 5, ?, ?,"
        " 0, 1)",
        (
            chunk_id,
            f"chunkv_{content_hash}",
            chunk_id,
            content_hash,
            f"text of {content_hash}",
        ),
    )


def _opt_in(connection: sqlite3.Connection, kind: EmbeddingProviderKind) -> None:
    ProviderPolicyStore(connection).set(
        ProviderPolicy(
            repository_id="repo_1",
            embedding_provider=kind,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )


def _embedder(
    connection: sqlite3.Connection,
    provider: object,
    store: InMemoryVectorStore | None = None,
) -> SnapshotEmbedder:
    return SnapshotEmbedder(
        connection=connection,
        vectors=store or InMemoryVectorStore(),
        build_provider=lambda policy: provider,  # type: ignore[arg-type,return-value]
        now=lambda: _NOW,
    )


# --- the disabled default ------------------------------------------------


def test_a_repository_that_opted_into_nothing_embeds_nothing(
    connection: sqlite3.Connection,
) -> None:
    """The default path, run on every index of every installation."""
    _chunk(connection, "chunk_a", "hash_a")
    provider = FakeProvider()

    result = _embedder(connection, provider).embed_snapshot("repo_1", "snap_1")

    assert provider.embedded == []
    assert result.skipped_because_disabled is True
    assert result.namespace_id is None


def test_a_disabled_repository_reports_no_coverage_rather_than_zero_coverage(
    connection: sqlite3.Connection,
) -> None:
    """Zero would read as "indexed, nothing found". `None` says the question
    does not apply — a repository with no provider is not missing coverage."""
    _chunk(connection, "chunk_a", "hash_a")

    result = _embedder(connection, FakeProvider()).embed_snapshot("repo_1", "snap_1")

    assert result.coverage is None


def test_no_namespace_is_created_for_a_disabled_repository(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")

    _embedder(connection, FakeProvider()).embed_snapshot("repo_1", "snap_1")

    assert NamespaceStore(connection).list_all() == ()


# --- the enabled path ----------------------------------------------------


def test_opting_in_embeds_the_snapshots_chunks(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _chunk(connection, "chunk_b", "hash_b")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    provider = FakeProvider()
    vectors = InMemoryVectorStore()

    result = _embedder(connection, provider, vectors).embed_snapshot(
        "repo_1", "snap_1"
    )

    assert sorted(provider.embedded) == ["text of hash_a", "text of hash_b"]
    assert result.embedded == 2
    assert result.coverage == pytest.approx(1.0)
    assert vectors.count(result.namespace_id or "") == 2


def test_the_namespace_is_created_from_the_providers_own_identity(
    connection: sqlite3.Connection,
) -> None:
    """Not from configuration. The namespace has to describe the vectors that
    are actually in it, so it is derived from the provider that produced
    them."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)

    result = _embedder(connection, FakeProvider()).embed_snapshot("repo_1", "snap_1")

    namespace = NamespaceStore(connection).get(result.namespace_id or "")
    assert namespace is not None
    assert namespace.model_id == "fake"
    assert namespace.dimensions == 3
    assert namespace.normalization_version == "l2_v1"


def test_re_embedding_an_unchanged_snapshot_costs_nothing(
    connection: sqlite3.Connection,
) -> None:
    """The watcher reindexes all day. If every index re-embedded the corpus,
    a repository would burn a provider budget doing no work."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    provider = FakeProvider()
    embedder = _embedder(connection, provider)
    embedder.embed_snapshot("repo_1", "snap_1")
    provider.embedded.clear()

    result = embedder.embed_snapshot("repo_1", "snap_1")

    assert provider.embedded == []
    assert result.embedded == 0
    assert result.reused == 1
    assert result.coverage == pytest.approx(1.0)


def test_only_the_changed_chunk_is_embedded_after_an_edit(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _chunk(connection, "chunk_b", "hash_b")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    provider = FakeProvider()
    embedder = _embedder(connection, provider)
    embedder.embed_snapshot("repo_1", "snap_1")
    provider.embedded.clear()

    connection.execute(
        "UPDATE chunks SET content_hash = 'hash_b_edited',"
        " retrieval_text = 'text of hash_b_edited'"
        " WHERE logical_chunk_id = 'chunk_b'"
    )
    result = embedder.embed_snapshot("repo_1", "snap_1")

    assert provider.embedded == ["text of hash_b_edited"]
    assert result.reused == 1


# --- failure must not reach the snapshot ---------------------------------


def test_a_provider_that_cannot_be_built_warns_instead_of_raising(
    connection: sqlite3.Connection,
) -> None:
    """The user switched the setting on before installing the extra. The index
    that follows must still succeed — the snapshot is already active, and a
    deterministic product does not need this provider to answer."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)

    def explode(policy: object) -> object:
        raise ProviderUnavailableError("no extra installed")

    embedder = SnapshotEmbedder(
        connection=connection,
        vectors=InMemoryVectorStore(),
        build_provider=explode,  # type: ignore[arg-type]
        now=lambda: _NOW,
    )

    result = embedder.embed_snapshot("repo_1", "snap_1")

    assert result.warning == "SEMANTIC_PROVIDER_UNAVAILABLE"
    assert result.embedded == 0


def test_a_provider_that_fails_mid_batch_warns_and_records(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)

    result = _embedder(connection, ExplodingProvider()).embed_snapshot(
        "repo_1", "snap_1"
    )

    assert result.failed == 1
    assert result.warning == "SEMANTIC_EMBEDDING_INCOMPLETE"
    assert result.coverage == pytest.approx(0.0)


def test_a_failed_run_leaves_the_work_visible_for_the_next_one(
    connection: sqlite3.Connection,
) -> None:
    """Crash safety, at the level that matters: work that did not finish must
    be findable as unfinished, not indistinguishable from work never queued."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    _embedder(connection, ExplodingProvider()).embed_snapshot("repo_1", "snap_1")

    namespace = NamespaceStore(connection).get_active()
    assert namespace is not None
    remaining = EmbeddingStore(connection).missing_content_hashes(
        namespace.namespace_id, content_hashes=("hash_a",)
    )

    assert remaining == ("hash_a",)


def test_a_failed_chunk_is_retried_and_can_succeed(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    vectors = InMemoryVectorStore()
    _embedder(connection, ExplodingProvider(), vectors).embed_snapshot(
        "repo_1", "snap_1"
    )

    provider = FakeProvider()
    result = _embedder(connection, provider, vectors).embed_snapshot(
        "repo_1", "snap_1"
    )

    assert provider.embedded == ["text of hash_a"]
    assert result.coverage == pytest.approx(1.0)


def test_a_vector_store_that_refuses_does_not_lose_the_embedding_record(
    connection: sqlite3.Connection,
) -> None:
    """If the vector write fails, the record must not claim `embedded` — the
    next run would skip content that has no vector, and the gap would be
    permanent and silent."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)

    class RefusingStore(InMemoryVectorStore):
        def upsert(self, namespace_id: str, records: object) -> None:
            raise OSError("disk full")

    result = _embedder(connection, FakeProvider(), RefusingStore()).embed_snapshot(
        "repo_1", "snap_1"
    )

    assert result.warning == "SEMANTIC_EMBEDDING_INCOMPLETE"
    namespace = NamespaceStore(connection).get_active()
    assert namespace is not None
    assert EmbeddingStore(connection).missing_content_hashes(
        namespace.namespace_id, content_hashes=("hash_a",)
    ) == ("hash_a",)


# --- coverage ------------------------------------------------------------


def test_coverage_is_computed_not_stored(connection: sqlite3.Connection) -> None:
    """Derived from the chunks and the cache at read time. A denormalized
    column would be one more thing that can disagree with the truth, and
    freshness is the product's third question."""
    _chunk(connection, "chunk_a", "hash_a")
    _chunk(connection, "chunk_b", "hash_b")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    _embedder(connection, FakeProvider()).embed_snapshot("repo_1", "snap_1")

    _chunk(connection, "chunk_c", "hash_c")

    coverage = read_coverage(connection, "repo_1", "snap_1")
    assert coverage is not None
    assert coverage.total == 3
    assert coverage.embedded == 2
    assert coverage.ratio == pytest.approx(2 / 3)


def test_coverage_of_an_empty_snapshot_is_complete_not_undefined(
    connection: sqlite3.Connection,
) -> None:
    """Nothing to embed is fully embedded. Reporting 0.0 would show a partial
    freshness banner on a repository with nothing in it."""
    _opt_in(connection, EmbeddingProviderKind.LOCAL)

    coverage = read_coverage(connection, "repo_1", "snap_1")

    assert coverage is not None
    assert coverage.ratio == pytest.approx(1.0)


def test_coverage_is_none_when_no_provider_is_enabled(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")

    assert read_coverage(connection, "repo_1", "snap_1") is None


def test_coverage_counts_only_this_snapshots_content(
    connection: sqlite3.Connection,
) -> None:
    """Another snapshot's embedded chunks must not inflate this one. Coverage
    is a claim about the snapshot being answered from."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    _embedder(connection, FakeProvider()).embed_snapshot("repo_1", "snap_1")

    connection.execute(
        "INSERT INTO snapshots ("
        " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
        " working_tree_fingerprint, file_count, parsed_file_count,"
        " skipped_file_count, parse_error_count, parser_bundle_version,"
        " index_version, created_at, activated_at"
        ") VALUES ('snap_2', 'repo_1', 'discovered', NULL, NULL, 0, 'fp2', 1, 1,"
        " 0, 0, '1.0.0', '1.0.0', '2026-07-29T01:00:00Z', NULL)"
    )
    connection.execute(
        "INSERT INTO files ("
        " snapshot_id, file_id, relative_path, display_path, content_hash,"
        " size_bytes, line_count, language, classification"
        ") VALUES ('snap_2', 'file_1', 'a.py', 'a.py', 'fh', 1, 10, 'python',"
        " 'source_code')"
    )
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES ('snap_2', 'chunk_z', 'chunkv_z', 'file_1', NULL, 'symbol',"
        " 'z', '', 1, 5, 'hash_never_embedded', 'text', 0, 1)"
    )

    coverage = read_coverage(connection, "repo_1", "snap_2")

    assert coverage is not None
    assert coverage.total == 1
    assert coverage.embedded == 0


def test_pending_work_is_reported_separately_from_failed_work(
    connection: sqlite3.Connection,
) -> None:
    """They need different remedies: pending resolves itself, failed needs
    someone told. Section 4.1 — say what CodeAtlas does not know."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    _embedder(connection, ExplodingProvider()).embed_snapshot("repo_1", "snap_1")

    coverage = read_coverage(connection, "repo_1", "snap_1")

    assert coverage is not None
    assert coverage.failed == 1
    assert coverage.embedded == 0


def test_an_embedding_status_is_one_of_the_three_declared_states(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection, EmbeddingProviderKind.LOCAL)
    _embedder(connection, FakeProvider()).embed_snapshot("repo_1", "snap_1")

    namespace = NamespaceStore(connection).get_active()
    assert namespace is not None
    rows = connection.execute(
        "SELECT DISTINCT status FROM embeddings WHERE namespace_id = ?",
        (namespace.namespace_id,),
    ).fetchall()

    assert {row[0] for row in rows} <= {status.value for status in EmbeddingStatus}
