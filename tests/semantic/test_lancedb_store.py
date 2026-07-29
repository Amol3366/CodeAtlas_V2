"""The LanceDB adapter, held to the same behaviours as the in-memory store.

The deterministic suite runs against `InMemoryVectorStore`, so if the two ever
meant different things, every test above this one would be verifying a store
that is not the one shipping. That is what this file exists to prevent: the
same assertions, against a real LanceDB directory on disk.

Runs only when the `semantic-local` extra is installed (see the root conftest).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.semantic.vector_store import (
    InMemoryVectorStore,
    VectorRecord,
    build_lancedb_store,
)

_NS = "fake_3d_l2-v1"


@pytest.fixture
def store(tmp_path: Path):  # type: ignore[no-untyped-def]
    return build_lancedb_store(tmp_path / "vectors")


def test_an_upserted_vector_is_found_by_itself(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    [match] = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert match.embedding_key == "emb_a"
    assert match.content_hash == "hash_a"
    assert match.score == pytest.approx(1.0, abs=1e-5)


def test_results_are_ordered_by_similarity(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(
        _NS,
        [
            VectorRecord("emb_far", "hash_far", [0.0, 1.0, 0.0]),
            VectorRecord("emb_near", "hash_near", [1.0, 0.0, 0.0]),
        ],
    )

    matches = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert [match.embedding_key for match in matches] == ["emb_near", "emb_far"]


def test_writing_the_same_key_twice_replaces_rather_than_duplicates(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [0.0, 1.0, 0.0])])

    matches = store.search(_NS, [0.0, 1.0, 0.0], limit=10)

    assert store.count(_NS) == 1
    assert matches[0].score == pytest.approx(1.0, abs=1e-5)


def test_a_search_of_an_unknown_namespace_is_empty_not_an_error(store) -> None:  # type: ignore[no-untyped-def]
    assert store.search("never_written_1d_v", [1.0], limit=5) == ()


def test_namespaces_do_not_see_each_other(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.upsert("other_3d_l2-v1", [VectorRecord("emb_b", "hash_b", [1.0, 0.0, 0.0])])

    matches = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert [match.embedding_key for match in matches] == ["emb_a"]


def test_deleting_a_namespace_leaves_the_others_alone(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.upsert("doomed_3d_l2-v1", [VectorRecord("emb_b", "hash_b", [1.0, 0.0, 0.0])])

    store.delete_namespace("doomed_3d_l2-v1")

    assert store.count(_NS) == 1
    assert store.count("doomed_3d_l2-v1") == 0


def test_new_writes_land_in_delta_and_are_searchable_immediately(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    assert store.delta_count(_NS) == 1
    assert store.base_count(_NS) == 0
    assert len(store.search(_NS, [1.0, 0.0, 0.0], limit=10)) == 1


def test_search_spans_base_and_delta(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_old", "hash_old", [1.0, 0.0, 0.0])])
    store.compact(_NS)
    store.upsert(_NS, [VectorRecord("emb_new", "hash_new", [0.9, 0.1, 0.0])])

    matches = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert {match.embedding_key for match in matches} == {"emb_old", "emb_new"}


def test_compaction_moves_delta_into_base_without_changing_results(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(
        _NS,
        [
            VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0]),
            VectorRecord("emb_b", "hash_b", [0.0, 1.0, 0.0]),
        ],
    )
    def ranking() -> list[str]:
        return [
            match.embedding_key
            for match in store.search(_NS, [1.0, 0.0, 0.0], limit=10)
        ]

    before = ranking()

    store.compact(_NS)

    assert store.delta_count(_NS) == 0
    assert store.base_count(_NS) == 2
    assert ranking() == before


def test_a_delta_write_supersedes_the_same_key_in_base(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.compact(_NS)
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [0.0, 1.0, 0.0])])

    matches = store.search(_NS, [0.0, 1.0, 0.0], limit=10)

    assert len(matches) == 1
    assert matches[0].score == pytest.approx(1.0, abs=1e-5)


def test_a_vector_of_the_wrong_width_is_refused(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    with pytest.raises(ValueError):
        store.upsert(_NS, [VectorRecord("emb_b", "hash_b", [1.0, 0.0])])


def test_writing_nothing_is_harmless(store) -> None:  # type: ignore[no-untyped-def]
    store.upsert(_NS, [])

    assert store.count(_NS) == 0


def test_vectors_survive_reopening_the_directory(tmp_path: Path) -> None:
    """The in-memory store cannot check this, and it is the whole reason to use
    a real one: an index built yesterday has to still be there today."""
    directory = tmp_path / "vectors"
    first = build_lancedb_store(directory)
    first.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    reopened = build_lancedb_store(directory)

    assert reopened.count(_NS) == 1
    assert reopened.search(_NS, [1.0, 0.0, 0.0], limit=5)[0].content_hash == "hash_a"


def test_a_row_carries_no_repository_content(tmp_path: Path) -> None:
    """ADR-0009 decision 3: this store holds derived data only. A path, an
    excerpt, or a line range here would be a second copy of the repository
    outside the database that governs snapshot membership."""
    directory = tmp_path / "vectors"
    store = build_lancedb_store(directory)
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    import lancedb

    table = lancedb.connect(str(directory)).open_table(f"{_NS}__delta")

    assert set(table.schema.names) == {"embedding_key", "content_hash", "vector"}


def test_the_two_implementations_rank_identically(tmp_path: Path) -> None:
    """The parity claim stated directly. If these ever disagree, the
    deterministic suite is verifying a store that is not the one shipping."""
    records = [
        VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0]),
        VectorRecord("emb_b", "hash_b", [0.6, 0.8, 0.0]),
        VectorRecord("emb_c", "hash_c", [0.0, 0.0, 1.0]),
    ]
    memory = InMemoryVectorStore()
    memory.upsert(_NS, records)
    lance = build_lancedb_store(tmp_path / "vectors")
    lance.upsert(_NS, records)

    query = [0.9, 0.4, 0.1]
    from_memory = [match.embedding_key for match in memory.search(_NS, query, limit=3)]
    from_lance = [match.embedding_key for match in lance.search(_NS, query, limit=3)]

    assert from_memory == from_lance
