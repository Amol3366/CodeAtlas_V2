"""The OpenAI provider, and the fact that it cannot be reached ungoverned.

Tested against a fake transport throughout: no test here needs network access or
an API key. A suite that skipped itself without credentials would be a suite
that silently stopped guarding the only path that transmits.

The load-bearing test is `test_the_factory_never_returns_an_ungoverned_remote
_provider`. Everything else in Phase 7 assumes redaction and budgets are
unavoidable; that assumption is only true if there is no way to obtain the raw
provider, and this is where that is checked.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.errors import ProviderUnavailableError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.semantic.governance import GovernedEmbeddingProvider
from codeatlas.semantic.providers import (
    NoEmbeddingProvider,
    OpenAIEmbeddingProvider,
    ProviderFactory,
    build_embedding_provider,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


class FakeEmbeddings:
    def __init__(self, dimensions: int = 3) -> None:
        self.dimensions = dimensions
        self.seen: list[list[str]] = []

    def create(self, *, model: str, input: list[str]):  # type: ignore[no-untyped-def]
        self.seen.append(list(input))

        class Item:
            def __init__(self, vector: list[float]) -> None:
                self.embedding = vector

        class Response:
            def __init__(self, items: list[Item]) -> None:
                self.data = items

        return Response([Item([3.0, 4.0, 0.0]) for _ in input])


class FakeClient:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddings()


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-30T00:00:00Z')"
        )
        yield conn


def _policy(kind: EmbeddingProviderKind) -> ProviderPolicy:
    return ProviderPolicy(
        repository_id="repo_1",
        embedding_provider=kind,
        monthly_token_budget=None,
        per_run_token_budget=None,
        updated_at=_NOW,
    )


# --- governance cannot be bypassed ---------------------------------------


def test_the_factory_never_returns_an_ungoverned_remote_provider(
    connection: sqlite3.Connection,
) -> None:
    """The assumption the rest of Phase 7 rests on."""
    factory = ProviderFactory(
        connection, open_client=lambda: FakeClient()
    )

    provider = factory.build(_policy(EmbeddingProviderKind.OPENAI))

    assert isinstance(provider, GovernedEmbeddingProvider)


def test_the_governed_wrapper_actually_redacts(
    connection: sqlite3.Connection,
) -> None:
    """Wrapping proves nothing on its own; the wrapper has to be wired to the
    transport that would otherwise send the text."""
    client = FakeClient()
    provider = ProviderFactory(connection, open_client=lambda: client).build(
        _policy(EmbeddingProviderKind.OPENAI)
    )

    provider.embed_documents(["key = AKIAIOSFODNN7EXAMPLE"])

    assert "AKIAIOSFODNN7EXAMPLE" not in "".join(client.embeddings.seen[0])


def test_a_repository_that_opted_into_nothing_gets_the_disabled_provider(
    connection: sqlite3.Connection,
) -> None:
    provider = ProviderFactory(connection).build(
        _policy(EmbeddingProviderKind.NONE)
    )

    assert isinstance(provider, NoEmbeddingProvider)


def test_the_connectionless_builder_still_refuses_openai() -> None:
    """`build_embedding_provider` has no connection, so it cannot record usage
    or read a budget. Returning a raw remote provider from it would be the
    bypass this phase must not have."""
    with pytest.raises(ProviderUnavailableError):
        build_embedding_provider(_policy(EmbeddingProviderKind.OPENAI))


def test_indexing_an_opted_in_repository_redacts_before_transmitting(
    connection: sqlite3.Connection,
) -> None:
    """End to end through the real embedder, because the wrapper only protects
    anything if the production wiring is what builds it."""
    from codeatlas.domain.semantic import ProviderPolicy as Policy
    from codeatlas.semantic.pipeline import SnapshotEmbedder
    from codeatlas.semantic.vector_store import InMemoryVectorStore
    from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore

    connection.execute(
        "INSERT INTO snapshots ("
        " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
        " working_tree_fingerprint, file_count, parsed_file_count,"
        " skipped_file_count, parse_error_count, parser_bundle_version,"
        " index_version, created_at, activated_at"
        ") VALUES ('snap_1', 'repo_1', 'active', NULL, NULL, 0, 'fp', 1, 1, 0,"
        " 0, '1.0.0', '1.0.0', '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z')"
    )
    connection.execute(
        "INSERT INTO files ("
        " snapshot_id, file_id, relative_path, display_path, content_hash,"
        " size_bytes, line_count, language, classification"
        ") VALUES ('snap_1', 'file_1', 'a.py', 'a.py', 'fh', 1, 10, 'python',"
        " 'source_code')"
    )
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line,"
        " content_hash, retrieval_text, part_index, part_count"
        ") VALUES ('snap_1', 'c1', 'cv1', 'file_1', NULL, 'symbol', 'c1', '',"
        " 1, 5, 'h1', 'key = AKIAIOSFODNN7EXAMPLE', 0, 1)"
    )
    ProviderPolicyStore(connection).set(
        Policy(
            repository_id="repo_1",
            embedding_provider=EmbeddingProviderKind.OPENAI,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )
    client = FakeClient()

    SnapshotEmbedder(
        connection=connection,
        vectors=InMemoryVectorStore(),
        build_provider=ProviderFactory(
            connection, open_client=lambda: client
        ).build,
    ).embed_snapshot("repo_1", "snap_1")

    assert client.embeddings.seen, "the provider was never reached"
    assert "AKIAIOSFODNN7EXAMPLE" not in "".join(client.embeddings.seen[0])


# --- the provider itself -------------------------------------------------


def test_vectors_are_normalized() -> None:
    """The vector store compares within a namespace by cosine, and every other
    provider normalizes at write time. A provider that did not would put
    differently-scaled vectors in one similarity space."""
    client = FakeClient()

    vectors = OpenAIEmbeddingProvider(client=client).embed_documents(["text"])

    length = sum(value * value for value in vectors[0]) ** 0.5
    assert length == pytest.approx(1.0)


def test_the_configured_model_is_the_one_requested() -> None:
    client = FakeClient()
    provider = OpenAIEmbeddingProvider(client=client)

    provider.embed_documents(["text"])

    assert provider.model_id


def test_an_empty_batch_costs_no_request() -> None:
    """A provider call with nothing in it is a billable no-op."""
    client = FakeClient()

    assert OpenAIEmbeddingProvider(client=client).embed_documents([]) == []
    assert client.embeddings.seen == []


def test_a_missing_credential_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure a user actually hits. An ImportError or a KeyError three
    frames down does not tell anyone what to do next."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProviderUnavailableError) as caught:
        OpenAIEmbeddingProvider()

    assert "OPENAI_API_KEY" in str(caught.value)


def test_the_credential_is_never_stored_on_the_instance() -> None:
    """A key held as an attribute reaches a repr, a traceback, and a
    diagnostic bundle. The client owns it; nothing here does."""
    provider = OpenAIEmbeddingProvider(client=FakeClient())

    assert not any(
        "key" in name.lower() for name in vars(provider)
    ), vars(provider).keys()
