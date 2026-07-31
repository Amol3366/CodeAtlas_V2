"""The semantic retrieval channel, and the ways it is allowed to fail.

Gate condition 5 is the reason most of this file exists. A semantic channel that
raises, or that returns nothing without saying so, would turn an optional recall
layer into a way to lose a deterministic answer. So every failure the provider
and the vector store can produce is tested for the same outcome: no candidates,
a named warning, and no exception.

The other half is gate condition 4. A vector that is physically present but not
a member of the snapshot being answered from must never become a candidate —
citing code that is not in the snapshot is the one failure the evidence contract
exists to prevent, and the vector store is precisely the component that cannot
be trusted to forget things promptly.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.errors import ProviderUnavailableError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.retrieval.semantic import (
    SemanticSearchRequest,
    SemanticSearchService,
)
from codeatlas.semantic.pipeline import SnapshotEmbedder
from codeatlas.semantic.vector_store import InMemoryVectorStore
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore

_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)

# Three orthogonal directions, so "which candidate ranked first" is a fact about
# similarity rather than about dict ordering.
_ALPHA = [1.0, 0.0, 0.0]
_BETA = [0.0, 1.0, 0.0]
_ELSEWHERE = [0.0, 0.0, 1.0]


class DirectionalProvider:
    """Maps declared texts to declared unit vectors.

    A fake, but not an arbitrary one: real ranking behaviour is what is under
    test, so the vectors have to make one candidate genuinely closer than
    another rather than merely different.
    """

    model_id = "fake"
    dimensions = 3
    normalization_version = "l2_v1"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.queries_embedded: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(text, list(_ELSEWHERE)) for text in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.queries_embedded.extend(texts)
        return self.embed_documents(texts)


class FailingProvider(DirectionalProvider):
    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        raise TimeoutError("the provider did not answer")


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-30T00:00:00Z')"
        )
        _snapshot(conn, "snap_1", state="active")
        conn.execute(
            "INSERT INTO files ("
            " snapshot_id, file_id, relative_path, display_path, content_hash,"
            " size_bytes, line_count, language, classification"
            ") VALUES ('snap_1', 'file_1', 'a.py', 'a.py', 'fh', 1, 10, 'python',"
            " 'source_code')"
        )
        yield conn


def _snapshot(
    connection: sqlite3.Connection, snapshot_id: str, *, state: str
) -> None:
    connection.execute(
        "INSERT INTO snapshots ("
        " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
        " working_tree_fingerprint, file_count, parsed_file_count,"
        " skipped_file_count, parse_error_count, parser_bundle_version,"
        " index_version, created_at, activated_at"
        ") VALUES (?, 'repo_1', ?, NULL, NULL, 0, 'fp', 1, 1, 0, 0, '1.0.0',"
        " '1.0.0', '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z')",
        (snapshot_id, state),
    )


def _chunk(
    connection: sqlite3.Connection,
    chunk_id: str,
    content_hash: str,
    *,
    snapshot_id: str = "snap_1",
    text: str | None = None,
    start_line: int = 1,
    end_line: int = 5,
) -> None:
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES (?, ?, ?, 'file_1', NULL, 'symbol', ?, '', ?, ?, ?, ?, 0, 1)",
        (
            snapshot_id,
            chunk_id,
            f"chunkv_{content_hash}",
            chunk_id,
            start_line,
            end_line,
            content_hash,
            text if text is not None else f"text of {content_hash}",
        ),
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


def _index(
    connection: sqlite3.Connection,
    provider: DirectionalProvider,
    vectors: InMemoryVectorStore,
    *,
    snapshot_id: str = "snap_1",
) -> None:
    SnapshotEmbedder(
        connection=connection,
        vectors=vectors,
        build_provider=lambda policy: provider,
        now=lambda: _NOW,
    ).embed_snapshot("repo_1", snapshot_id)


def _service(
    connection: sqlite3.Connection,
    provider: object,
    vectors: InMemoryVectorStore,
) -> SemanticSearchService:
    return SemanticSearchService(
        connection=connection,
        vectors=vectors,
        build_provider=lambda policy: provider,  # type: ignore[arg-type,return-value]
    )


def _request(query: str = "alpha", limit: int = 10) -> SemanticSearchRequest:
    return SemanticSearchRequest(
        repository_id="repo_1",
        snapshot_id="snap_1",
        query=query,
        limit=limit,
    )


# --- the disabled default ------------------------------------------------


def test_a_repository_that_opted_into_nothing_returns_nothing_and_warns_nothing(
    connection: sqlite3.Connection,
) -> None:
    """The default path on every installation. Silence is correct here: a
    repository that opted into no provider is not missing a feature, so a
    warning would appear on every answer and mean nothing."""
    _chunk(connection, "chunk_a", "hash_a")
    provider = DirectionalProvider({})

    result = _service(connection, provider, InMemoryVectorStore()).search(_request())

    assert result.candidates == ()
    assert result.warnings == ()
    assert result.enabled is False
    assert provider.queries_embedded == []


# --- the enabled path ----------------------------------------------------


def test_candidates_come_back_ranked_by_similarity(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a", text="alpha body")
    _chunk(
        connection, "chunk_b", "hash_b", text="beta body", start_line=20, end_line=25
    )
    _opt_in(connection)
    provider = DirectionalProvider(
        {"alpha body": _ALPHA, "beta body": _BETA, "alpha": _ALPHA}
    )
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors)

    result = _service(connection, provider, vectors).search(_request("alpha"))

    assert [candidate.logical_chunk_id for candidate in result.candidates] == [
        "chunk_a",
        "chunk_b",
    ]
    assert result.candidates[0].score > result.candidates[1].score


def test_a_candidate_carries_the_lines_needed_to_cite_it(
    connection: sqlite3.Connection,
) -> None:
    """A candidate has to be able to become evidence. Returning bare hashes
    would push a lookup onto every caller — the kind that gets skipped once and
    produces a citation nobody validated."""
    _chunk(
        connection, "chunk_a", "hash_a", text="alpha body", start_line=7, end_line=11
    )
    _opt_in(connection)
    provider = DirectionalProvider({"alpha body": _ALPHA, "alpha": _ALPHA})
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors)

    result = _service(connection, provider, vectors).search(_request("alpha"))

    candidate = result.candidates[0]
    assert candidate.file_id == "file_1"
    assert (candidate.start_line, candidate.end_line) == (7, 11)
    assert candidate.snapshot_id == "snap_1"


def test_the_limit_bounds_what_comes_back(connection: sqlite3.Connection) -> None:
    for index in range(5):
        _chunk(connection, f"chunk_{index}", f"hash_{index}", text=f"body {index}")
    _opt_in(connection)
    provider = DirectionalProvider({f"body {index}": _ALPHA for index in range(5)})
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors)

    result = _service(connection, provider, vectors).search(_request(limit=2))

    assert len(result.candidates) == 2


# --- membership decides eligibility, not the vector store ----------------


def test_a_vector_whose_content_left_the_snapshot_is_not_a_candidate(
    connection: sqlite3.Connection,
) -> None:
    """Gate condition 4. The vector store still physically holds the vector;
    SQLite membership is what makes it ineligible. Deleting from the vector
    store instead would make correctness depend on winning a race."""
    _chunk(connection, "chunk_a", "hash_a", text="alpha body")
    _opt_in(connection)
    provider = DirectionalProvider({"alpha body": _ALPHA, "alpha": _ALPHA})
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors)

    # The content leaves the snapshot. The vector is deliberately left behind.
    connection.execute("DELETE FROM chunks WHERE logical_chunk_id = 'chunk_a'")

    result = _service(connection, provider, vectors).search(_request("alpha"))

    assert result.candidates == ()
    assert vectors.count(_active_namespace(connection)) == 1


def test_another_snapshots_content_is_not_a_candidate(
    connection: sqlite3.Connection,
) -> None:
    """One embedding namespace spans every snapshot, because content hashes are
    shared on purpose. Snapshot isolation therefore has to come from the join,
    and this proves it does."""
    _chunk(connection, "chunk_a", "hash_a", text="alpha body")
    _snapshot(connection, "snap_2", state="superseded")
    connection.execute(
        "INSERT INTO files ("
        " snapshot_id, file_id, relative_path, display_path, content_hash,"
        " size_bytes, line_count, language, classification"
        ") VALUES ('snap_2', 'file_1', 'a.py', 'a.py', 'fh', 1, 10, 'python',"
        " 'source_code')"
    )
    _chunk(connection, "chunk_old", "hash_old", snapshot_id="snap_2", text="alpha old")
    _opt_in(connection)
    provider = DirectionalProvider(
        {"alpha body": _ALPHA, "alpha old": _ALPHA, "alpha": _ALPHA}
    )
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors, snapshot_id="snap_1")
    _index(connection, provider, vectors, snapshot_id="snap_2")

    result = _service(connection, provider, vectors).search(_request("alpha"))

    assert [candidate.logical_chunk_id for candidate in result.candidates] == [
        "chunk_a"
    ]


# --- the fallback matrix -------------------------------------------------


def test_a_provider_that_cannot_be_built_warns_and_returns_nothing(
    connection: sqlite3.Connection,
) -> None:
    """The setting was switched on before the extra was installed."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection)

    def explode(policy: object) -> object:
        raise ProviderUnavailableError("no extra installed")

    service = SemanticSearchService(
        connection=connection,
        vectors=InMemoryVectorStore(),
        build_provider=explode,  # type: ignore[arg-type]
    )

    result = service.search(_request())

    assert result.candidates == ()
    assert result.warnings == ("SEMANTIC_PROVIDER_UNAVAILABLE",)
    assert result.enabled is True


def test_a_provider_that_fails_warns_and_returns_nothing(
    connection: sqlite3.Connection,
) -> None:
    """A timeout, a killed model process, an out-of-memory kill. None of them
    may reach the caller as an exception: the deterministic answer is already
    computed and must still be delivered."""
    _chunk(connection, "chunk_a", "hash_a", text="alpha body")
    _opt_in(connection)
    vectors = InMemoryVectorStore()
    _index(connection, DirectionalProvider({"alpha body": _ALPHA}), vectors)

    result = _service(connection, FailingProvider({}), vectors).search(_request())

    assert result.candidates == ()
    assert result.warnings == ("SEMANTIC_PROVIDER_FAILED",)


def test_a_vector_store_that_fails_warns_and_returns_nothing(
    connection: sqlite3.Connection,
) -> None:
    _chunk(connection, "chunk_a", "hash_a", text="alpha body")
    _opt_in(connection)
    provider = DirectionalProvider({"alpha body": _ALPHA, "alpha": _ALPHA})
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors)

    class RefusingStore(InMemoryVectorStore):
        def search(self, namespace_id: str, query_vector: object, *, limit: int):  # type: ignore[no-untyped-def]
            raise OSError("the vector directory is gone")

    refusing = RefusingStore()
    result = _service(connection, provider, refusing).search(_request())

    assert result.candidates == ()
    assert result.warnings == ("SEMANTIC_INDEX_UNAVAILABLE",)


def test_enabled_but_never_indexed_says_so_rather_than_failing(
    connection: sqlite3.Connection,
) -> None:
    """Every repository looks like this between opting in and the next index."""
    _chunk(connection, "chunk_a", "hash_a")
    _opt_in(connection)

    result = _service(
        connection, DirectionalProvider({}), InMemoryVectorStore()
    ).search(_request())

    assert result.candidates == ()
    assert result.warnings == ("SEMANTIC_INDEX_UNAVAILABLE",)
    assert result.enabled is True


def test_an_empty_query_is_not_sent_to_the_provider(
    connection: sqlite3.Connection,
) -> None:
    """Bounded input, Section 10.3. An empty query has no meaningful nearest
    neighbour, and paying a provider to discover that is waste."""
    _chunk(connection, "chunk_a", "hash_a", text="alpha body")
    _opt_in(connection)
    provider = DirectionalProvider({"alpha body": _ALPHA})
    vectors = InMemoryVectorStore()
    _index(connection, provider, vectors)
    provider.queries_embedded.clear()

    result = _service(connection, provider, vectors).search(_request("   "))

    assert result.candidates == ()
    assert provider.queries_embedded == []


def _active_namespace(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT namespace_id FROM embedding_namespaces WHERE status = 'active'"
    ).fetchone()
    assert row is not None
    return str(row[0])
