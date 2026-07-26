"""Chunk logical and version identity.

Chunk identity mirrors symbol identity: the logical ID answers "which chunk is
this" and survives edits, while the version ID answers "which exact content and
which chunking logic produced it". Phase 2's reuse claim rests entirely on that
split holding, so it is asserted here rather than assumed downstream.
"""

from __future__ import annotations

from codeatlas.domain.chunks import ChunkRole
from codeatlas.domain.ids import chunk_version_id, logical_chunk_id


def test_logical_chunk_id_is_deterministic_and_prefixed() -> None:
    first = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    second = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    assert first == second
    assert first.startswith("chunk_")


def test_chunk_version_id_is_deterministic_and_prefixed() -> None:
    logical = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    first = chunk_version_id(logical, "hash-1", "1.0.0", "1.0.0")
    second = chunk_version_id(logical, "hash-1", "1.0.0", "1.0.0")
    assert first == second
    assert first.startswith("chunkv_")


def test_editing_content_changes_only_the_chunk_version() -> None:
    logical = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    first = chunk_version_id(logical, "hash-1", "1.0.0", "1.0.0")
    second = chunk_version_id(logical, "hash-2", "1.0.0", "1.0.0")
    assert first != second
    assert logical == logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")


def test_chunker_version_participates_in_the_version_id() -> None:
    logical = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    assert chunk_version_id(logical, "h", "1.0.0", "1.0.0") != chunk_version_id(
        logical, "h", "1.0.0", "2.0.0"
    )


def test_parser_bundle_version_participates_in_the_version_id() -> None:
    logical = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    assert chunk_version_id(logical, "h", "1.0.0", "1.0.0") != chunk_version_id(
        logical, "h", "2.0.0", "1.0.0"
    )


def test_role_distinguishes_chunks_at_the_same_location() -> None:
    assert logical_chunk_id("repo_1", "src/a.py", "A", "symbol") != logical_chunk_id(
        "repo_1", "src/a.py", "A", "file_summary"
    )


def test_every_role_produces_a_distinct_logical_chunk() -> None:
    identities = {
        logical_chunk_id("repo_1", "src/a.py", "A", role.value) for role in ChunkRole
    }
    assert len(identities) == len(ChunkRole)


def test_repository_and_path_are_part_of_logical_identity() -> None:
    baseline = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    assert baseline != logical_chunk_id("repo_2", "src/a.py", "A.run", "symbol")
    assert baseline != logical_chunk_id("repo_1", "src/b.py", "A.run", "symbol")


def test_fields_cannot_collide_by_concatenation() -> None:
    assert logical_chunk_id("repo_1", "src/a.py", "A", "b") != logical_chunk_id(
        "repo_1", "src/a.py", "Ab", ""
    )
    logical = logical_chunk_id("repo_1", "src/a.py", "A.run", "symbol")
    assert chunk_version_id(logical, "a", "b", "c") != chunk_version_id(
        logical, "ab", "", "c"
    )
