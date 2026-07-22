"""Property + unit tests for content-addressed identity (Blueprint §4.3.5)."""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from codeatlas.domain.enums import ChunkRole
from codeatlas.domain.identity import (
    chunk_version_id,
    embedding_key,
    logical_chunk_id,
    stable_hash,
)

_parts = st.lists(st.one_of(st.text(), st.integers(), st.none()), max_size=6)


def test_stable_hash_is_deterministic() -> None:
    assert stable_hash("a", "b", None, 1) == stable_hash("a", "b", None, 1)


def test_stable_hash_is_order_sensitive() -> None:
    assert stable_hash("a", "b") != stable_hash("b", "a")


def test_stable_hash_has_no_boundary_collision() -> None:
    # Length-prefixing prevents ("a","b") from aliasing ("ab",) or ("ab","").
    assert stable_hash("a", "b") != stable_hash("ab")
    assert stable_hash("a", "b") != stable_hash("ab", "")


def test_none_distinct_from_empty_string() -> None:
    assert stable_hash(None) != stable_hash("")


def test_int_distinct_from_str() -> None:
    assert stable_hash(1) != stable_hash("1")


@given(_parts)
def test_stable_hash_deterministic_property(parts: list[str | int | None]) -> None:
    assert stable_hash(*parts) == stable_hash(*parts)


@given(_parts, _parts)
def test_distinct_inputs_yield_distinct_hashes(
    x: list[str | int | None], y: list[str | int | None]
) -> None:
    assume(x != y)
    assert stable_hash(*x) != stable_hash(*y)


# --- Derived identities -------------------------------------------------------


def test_logical_chunk_id_deterministic_and_prefixed() -> None:
    args = ("repo_1", "src/a.py", "A.method", ChunkRole.SYMBOL_IMPLEMENTATION)
    first = logical_chunk_id(*args)
    assert first == logical_chunk_id(*args)
    assert first.startswith("lc_")


def test_logical_chunk_id_accepts_none_qualified_name() -> None:
    a = logical_chunk_id("repo_1", "src/a.py", None, ChunkRole.FILE_SUMMARY)
    b = logical_chunk_id("repo_1", "src/a.py", "x", ChunkRole.FILE_SUMMARY)
    assert a != b


def test_chunk_version_id_changes_with_content() -> None:
    lc = logical_chunk_id("repo_1", "src/a.py", "f", ChunkRole.SYMBOL_IMPLEMENTATION)
    v1 = chunk_version_id(lc, "hash_a", "0.1.0", "0.1.0")
    v2 = chunk_version_id(lc, "hash_b", "0.1.0", "0.1.0")
    assert v1.startswith("cv_")
    assert v1 != v2
    # Same content + versions -> identical id (reuse across snapshots).
    assert v1 == chunk_version_id(lc, "hash_a", "0.1.0", "0.1.0")


def test_chunk_version_id_changes_with_parser_or_chunker_version() -> None:
    lc = logical_chunk_id("repo_1", "src/a.py", "f", ChunkRole.SYMBOL_IMPLEMENTATION)
    base = chunk_version_id(lc, "h", "0.1.0", "0.1.0")
    assert base != chunk_version_id(lc, "h", "0.2.0", "0.1.0")
    assert base != chunk_version_id(lc, "h", "0.1.0", "0.2.0")


def test_embedding_key_changes_with_model_but_not_answering() -> None:
    # Changing the embedding model/dims yields a new key (new namespace).
    k1 = embedding_key("hash", "model-a", 384, "0.1.0")
    k2 = embedding_key("hash", "model-b", 384, "0.1.0")
    k3 = embedding_key("hash", "model-a", 768, "0.1.0")
    assert k1.startswith("ek_")
    assert k1 != k2
    assert k1 != k3
    assert k1 == embedding_key("hash", "model-a", 384, "0.1.0")
