"""The content-hash embedding cache, against real SQLite.

This is gate condition 3 in executable form: a one-symbol edit must embed only
changed unique content, and unchanged content must reuse what exists. The
provider is a fake that *counts what it was asked to embed*, because the
assertion that matters is not "the right vectors came back" but "the wrong work
never happened".

The fake is a fake and not a mock of SQLite: the store is real. Section 19.1
says not to mock the local dependency when it is cheap, and a cache tested
against a mocked store would prove nothing about the query that decides what is
missing.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.errors import ProviderDisabledError
from codeatlas.domain.ids import embedding_namespace_id
from codeatlas.domain.semantic import (
    EmbeddingNamespace,
    EmbeddingStatus,
    NamespaceStatus,
)
from codeatlas.semantic.cache import EmbeddingCache, EmbeddingRequest
from codeatlas.semantic.providers import NoEmbeddingProvider
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import EmbeddingStore, NamespaceStore

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


class CountingProvider:
    """Records every text it was asked to embed."""

    model_id = "fake"
    dimensions = 3
    normalization_version = "l2_v1"

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [[float(len(text)), 0.0, 1.0] for text in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class ExplodingProvider:
    model_id = "fake"
    dimensions = 3
    normalization_version = "l2_v1"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise TimeoutError("the provider went away")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        yield conn


@pytest.fixture
def namespace(connection: sqlite3.Connection) -> EmbeddingNamespace:
    value = EmbeddingNamespace(
        namespace_id=embedding_namespace_id("fake", 3, "l2_v1"),
        model_id="fake",
        dimensions=3,
        normalization_version="l2_v1",
        status=NamespaceStatus.ACTIVE,
        created_at=_NOW,
        activated_at=_NOW,
    )
    NamespaceStore(connection).add(value)
    return value


def _cache(
    connection: sqlite3.Connection,
    namespace: EmbeddingNamespace,
    provider: object,
) -> EmbeddingCache:
    return EmbeddingCache(
        provider=provider,  # type: ignore[arg-type]
        store=EmbeddingStore(connection),
        namespace=namespace,
        now=lambda: _NOW,
    )


def test_new_content_is_embedded_once(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    provider = CountingProvider()
    cache = _cache(connection, namespace, provider)

    result = cache.embed_missing([EmbeddingRequest("hash_a", "def a(): ...")])

    assert provider.embedded == ["def a(): ..."]
    assert set(result.vectors) == {"hash_a"}
    assert result.reused == ()


def test_unchanged_content_is_not_embedded_again(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """The cost contract. Re-indexing an untouched repository must cost nothing
    at the provider (blueprint 8.21)."""
    provider = CountingProvider()
    cache = _cache(connection, namespace, provider)
    request = EmbeddingRequest("hash_a", "def a(): ...")
    cache.embed_missing([request])
    provider.embedded.clear()

    result = cache.embed_missing([request])

    assert provider.embedded == []
    assert result.reused == ("hash_a",)
    assert result.vectors == {}


def test_a_one_symbol_edit_embeds_only_the_changed_symbol(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """The named gate condition, at the size a user's edit actually is."""
    provider = CountingProvider()
    cache = _cache(connection, namespace, provider)
    before = [
        EmbeddingRequest("hash_a", "def a(): ..."),
        EmbeddingRequest("hash_b", "def b(): ..."),
        EmbeddingRequest("hash_c", "def c(): ..."),
    ]
    cache.embed_missing(before)
    provider.embedded.clear()

    after = [
        EmbeddingRequest("hash_a", "def a(): ..."),
        EmbeddingRequest("hash_b_edited", "def b(): return 1"),
        EmbeddingRequest("hash_c", "def c(): ..."),
    ]
    result = cache.embed_missing(after)

    assert provider.embedded == ["def b(): return 1"]
    assert sorted(result.reused) == ["hash_a", "hash_c"]


def test_duplicate_content_within_one_batch_is_embedded_once(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """Two files with identical content — a vendored copy, a generated stub —
    share a content hash and therefore an embedding."""
    provider = CountingProvider()
    cache = _cache(connection, namespace, provider)

    cache.embed_missing(
        [
            EmbeddingRequest("same", "identical body"),
            EmbeddingRequest("same", "identical body"),
        ]
    )

    assert provider.embedded == ["identical body"]


def test_an_embedded_record_is_written_for_reuse_to_find(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    cache = _cache(connection, namespace, CountingProvider())

    cache.embed_missing([EmbeddingRequest("hash_a", "body")])

    store = EmbeddingStore(connection)
    assert store.count_embedded(namespace.namespace_id) == 1
    assert store.missing_content_hashes(
        namespace.namespace_id, content_hashes=("hash_a",)
    ) == ()


def test_a_provider_failure_is_recorded_and_does_not_propagate(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """Gate condition 5. A provider that times out must degrade to a useful
    deterministic result, which it cannot do if the exception reaches the
    indexing pipeline and fails the snapshot."""
    cache = _cache(connection, namespace, ExplodingProvider())

    result = cache.embed_missing([EmbeddingRequest("hash_a", "body")])

    assert result.failed == ("hash_a",)
    assert result.vectors == {}
    stored = EmbeddingStore(connection).get(result.keys["hash_a"])
    assert stored is not None
    assert stored.status is EmbeddingStatus.FAILED


def test_a_failure_code_is_stored_not_the_provider_message(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """A provider message can quote the payload it choked on, and payloads are
    repository content."""
    cache = _cache(connection, namespace, ExplodingProvider())

    result = cache.embed_missing([EmbeddingRequest("hash_a", "secret body")])

    stored = EmbeddingStore(connection).get(result.keys["hash_a"])
    assert stored is not None
    assert stored.failure_code == "PROVIDER_FAILED"
    assert "secret" not in (stored.failure_code or "")


def test_failed_content_is_attempted_again_on_the_next_run(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """A transient failure must not become permanent silence: a record left as
    `failed` is missing coverage, not covered."""
    failing = _cache(connection, namespace, ExplodingProvider())
    failing.embed_missing([EmbeddingRequest("hash_a", "body")])

    provider = CountingProvider()
    recovered = _cache(connection, namespace, provider)
    result = recovered.embed_missing([EmbeddingRequest("hash_a", "body")])

    assert provider.embedded == ["body"]
    assert set(result.vectors) == {"hash_a"}


def test_a_disabled_provider_produces_nothing_and_raises_nothing(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """The default installation runs this path on every index. It must be a
    quiet no-op, not an exception the indexer has to catch."""
    cache = _cache(connection, namespace, NoEmbeddingProvider())

    result = cache.embed_missing([EmbeddingRequest("hash_a", "body")])

    assert result.vectors == {}
    assert result.failed == ()
    assert result.skipped_because_disabled is True
    assert EmbeddingStore(connection).count(namespace.namespace_id) == 0


def test_a_disabled_provider_leaves_no_pending_rows_to_mislead_coverage(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """Writing `pending` rows for a repository that will never embed would
    report a coverage figure that could never reach 1.0."""
    cache = _cache(connection, namespace, NoEmbeddingProvider())

    cache.embed_missing([EmbeddingRequest("hash_a", "body")])

    assert EmbeddingStore(connection).count(namespace.namespace_id) == 0


def test_embedding_nothing_is_not_a_provider_call(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """An index that changed no chunk must not wake a model."""
    provider = CountingProvider()
    cache = _cache(connection, namespace, provider)

    result = cache.embed_missing([])

    assert provider.embedded == []
    assert result.vectors == {}


def test_a_vector_of_the_wrong_width_is_refused(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """A provider whose dimensions disagree with its namespace would put
    incomparable vectors in one similarity space (blueprint 4.7.6). The
    mismatch is caught here, before anything is written."""

    class WrongWidthProvider(CountingProvider):
        dimensions = 99

    with pytest.raises(ValueError):
        _cache(connection, namespace, WrongWidthProvider())


def test_the_disabled_path_never_calls_the_provider(
    connection: sqlite3.Connection, namespace: EmbeddingNamespace
) -> None:
    """Belt and braces: `NoEmbeddingProvider` raises if called, so reaching the
    assertion at all proves the cache checked before calling."""
    cache = _cache(connection, namespace, NoEmbeddingProvider())

    try:
        cache.embed_missing([EmbeddingRequest("hash_a", "body")])
    except ProviderDisabledError:  # pragma: no cover - the failure this guards
        pytest.fail("the cache called a disabled provider instead of skipping")
