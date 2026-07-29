"""The vector store interface, exercised through the in-memory implementation.

`InMemoryVectorStore` is a real implementation of the interface, not a mock: it
is what the deterministic test suite and the evaluation harness run against,
since LanceDB lives behind an optional extra. The LanceDB adapter is held to
these same behaviours in `tests/semantic/test_lancedb_store.py`, so the two
cannot drift into meaning different things.

Base and delta are the blueprint's 4.7.5 split: a large stable namespace and a
small recent one, so that a normal edit appends instead of rewriting.
"""

from __future__ import annotations

import pytest

from codeatlas.semantic.vector_store import InMemoryVectorStore, VectorRecord

_NS = "fake_3d_l2-v1"


def _store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


def test_an_upserted_vector_is_found_by_itself() -> None:
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    [match] = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert match.embedding_key == "emb_a"
    assert match.content_hash == "hash_a"
    assert match.score == pytest.approx(1.0)


def test_results_are_ordered_by_similarity() -> None:
    store = _store()
    store.upsert(
        _NS,
        [
            VectorRecord("emb_far", "hash_far", [0.0, 1.0, 0.0]),
            VectorRecord("emb_near", "hash_near", [1.0, 0.0, 0.0]),
        ],
    )

    matches = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert [match.embedding_key for match in matches] == ["emb_near", "emb_far"]


def test_the_limit_is_respected() -> None:
    store = _store()
    store.upsert(
        _NS,
        [VectorRecord(f"emb_{i}", f"hash_{i}", [1.0, 0.0, 0.0]) for i in range(10)],
    )

    assert len(store.search(_NS, [1.0, 0.0, 0.0], limit=3)) == 3


def test_writing_the_same_key_twice_replaces_rather_than_duplicates() -> None:
    """Re-embedding after a failed run must not leave two rows for one key: a
    duplicate would occupy two of the caller's limited result slots with the
    same content."""
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [0.0, 1.0, 0.0])])

    matches = store.search(_NS, [0.0, 1.0, 0.0], limit=10)

    assert store.count(_NS) == 1
    assert matches[0].score == pytest.approx(1.0)


def test_a_search_of_an_unknown_namespace_is_empty_not_an_error() -> None:
    """An installation that enabled a provider but has not indexed yet asks
    this question on its first query. It is an ordinary empty result."""
    assert _store().search("never_written_1d_v", [1.0], limit=5) == ()


def test_namespaces_do_not_see_each_other() -> None:
    """Two similarity spaces in one store. Mixing them is blueprint 4.7.6's
    named error, and it would be invisible: the scores are all plausible."""
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.upsert("other_3d_l2-v1", [VectorRecord("emb_b", "hash_b", [1.0, 0.0, 0.0])])

    matches = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert [match.embedding_key for match in matches] == ["emb_a"]


def test_deleting_a_namespace_leaves_the_others_alone() -> None:
    """Closing a rollback window after a model migration."""
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.upsert("doomed_3d_l2-v1", [VectorRecord("emb_b", "hash_b", [1.0, 0.0, 0.0])])

    store.delete_namespace("doomed_3d_l2-v1")

    assert store.count(_NS) == 1
    assert store.count("doomed_3d_l2-v1") == 0


# --- base and delta ------------------------------------------------------


def test_new_writes_land_in_delta_and_are_searchable_immediately() -> None:
    """The freshness contract: a chunk embedded after an edit must be findable
    without waiting for a compaction."""
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    assert store.delta_count(_NS) == 1
    assert store.base_count(_NS) == 0
    assert len(store.search(_NS, [1.0, 0.0, 0.0], limit=10)) == 1


def test_search_spans_base_and_delta() -> None:
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_old", "hash_old", [1.0, 0.0, 0.0])])
    store.compact(_NS)
    store.upsert(_NS, [VectorRecord("emb_new", "hash_new", [0.9, 0.1, 0.0])])

    matches = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    assert {match.embedding_key for match in matches} == {"emb_old", "emb_new"}


def test_compaction_moves_delta_into_base_without_changing_results() -> None:
    """Compaction is a storage decision. It must be invisible to retrieval —
    blueprint 4.7.5 only allows a base switch after validation for exactly this
    reason."""
    store = _store()
    store.upsert(
        _NS,
        [
            VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0]),
            VectorRecord("emb_b", "hash_b", [0.0, 1.0, 0.0]),
        ],
    )
    before = store.search(_NS, [1.0, 0.0, 0.0], limit=10)

    store.compact(_NS)

    assert store.delta_count(_NS) == 0
    assert store.base_count(_NS) == 2
    assert store.search(_NS, [1.0, 0.0, 0.0], limit=10) == before


def test_a_delta_write_supersedes_the_same_key_in_base() -> None:
    """Re-embedding content after a normalization change writes to delta while
    the old vector is still in base. Returning both would put two rows for one
    key in front of the caller, one of them stale."""
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])
    store.compact(_NS)
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [0.0, 1.0, 0.0])])

    matches = store.search(_NS, [0.0, 1.0, 0.0], limit=10)

    assert len(matches) == 1
    assert matches[0].score == pytest.approx(1.0)


def test_a_vector_of_the_wrong_width_is_refused() -> None:
    """Every vector in a namespace has to be the same width or the similarity
    is meaningless. Refusing at write time keeps the mistake out of the store
    rather than surfacing it as a strange ranking later."""
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    with pytest.raises(ValueError):
        store.upsert(_NS, [VectorRecord("emb_b", "hash_b", [1.0, 0.0])])


def test_a_query_of_the_wrong_width_is_refused() -> None:
    store = _store()
    store.upsert(_NS, [VectorRecord("emb_a", "hash_a", [1.0, 0.0, 0.0])])

    with pytest.raises(ValueError):
        store.search(_NS, [1.0, 0.0], limit=5)


def test_writing_nothing_is_harmless() -> None:
    """An index that changed no chunk reaches this with an empty batch."""
    store = _store()
    store.upsert(_NS, [])

    assert store.count(_NS) == 0
