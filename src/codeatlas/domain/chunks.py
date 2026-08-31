"""Retrieval chunks: the unit of lexical and, later, semantic recall.

A chunk is a bounded, citable region of a file that stands on its own as an
answer. It is derived from parsed structure, never from fixed-size splitting of
raw bytes, so its boundaries fall where a reader would expect: a whole function,
a whole heading section, a whole configuration key.

A chunk stores its *retrieval text* — a deterministic header plus bounded code —
not a second copy of the repository. Evidence is still read from disk and
verified against a content hash, so the chunk table can never become a stale
alternative source of truth about file contents.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum

from codeatlas.domain.ids import chunk_version_id, stable_hash


class ChunkRole(StrEnum):
    """What a chunk represents.

    The role participates in logical identity, so a file summary and a symbol
    covering the same lines remain distinct chunks rather than colliding.
    """

    FILE_SUMMARY = "file_summary"
    SYMBOL = "symbol"
    SYMBOL_PART = "symbol_part"
    DOCUMENT_SECTION = "document_section"
    CONFIG_KEY = "config_key"


@dataclass(frozen=True)
class LogicalChunk:
    """One chunk of one file, with the identity needed to reuse it.

    ``logical_chunk_id`` survives edits; ``chunk_version_id`` does not. That
    split is what lets an unchanged chunk be copied into a new snapshot instead
    of being recomputed.

    ``start_line`` and ``end_line`` are 1-based and inclusive, and always index
    the real source file, including for a split part of an oversized symbol.
    """

    logical_chunk_id: str
    chunk_version_id: str
    file_id: str
    symbol_id: str | None
    role: ChunkRole
    qualified_name: str
    heading_path: str
    start_line: int
    end_line: int
    content_hash: str
    retrieval_text: str
    part_index: int = 0
    part_count: int = 1


def ensure_unique_chunk_ids(
    chunks: tuple[LogicalChunk, ...],
    parser_bundle_version: str,
    chunker_version: str,
) -> tuple[LogicalChunk, ...]:
    """Give every chunk in one file a distinct ``(logical_chunk_id, part_index)``.

    The sibling of ``ensure_unique_symbol_ids``, and necessary for the same
    reason one layer down: ``logical_chunk_id`` is
    ``hash(repository_id, relative_path, qualified_name, chunk_role)``, which
    carries no more disambiguator than ``symbol_id`` did. Fixing only the
    symbols moved the failure from ``symbols`` to ``chunks`` rather than
    curing it -- a Python property and its setter produce two chunks with one
    id, and indexing still ended in ``UNIQUE constraint failed``.

    **A code chunk is disambiguated by its ``symbol_id``**, which is unique
    once ``ensure_unique_symbol_ids`` has run. That is better than an ordinal
    because it is *stable*: the chunk of an overload keeps its identity when a
    sibling is inserted above it, since the symbol it belongs to does. Document
    and configuration chunks carry no symbol, so there the ordinal carries it.

    As with symbols, the first member of a colliding group keeps the id it
    already had, so no chunk that can be stored today changes and no reindex is
    required.
    """
    counts: dict[tuple[str, int], int] = {}
    for chunk in chunks:
        key = (chunk.logical_chunk_id, chunk.part_index)
        counts[key] = counts.get(key, 0) + 1
    if all(count == 1 for count in counts.values()):
        return chunks

    order = sorted(
        range(len(chunks)),
        key=lambda index: (
            chunks[index].start_line,
            chunks[index].part_index,
            index,
        ),
    )
    seen_group: set[tuple[str, int]] = set()
    seen_discriminator: dict[tuple[str, int, str], int] = {}
    rewritten: dict[int, LogicalChunk] = {}

    for index in order:
        chunk = chunks[index]
        key = (chunk.logical_chunk_id, chunk.part_index)
        if counts[key] == 1:
            continue
        discriminator = chunk.symbol_id or ""
        ordinal_key = (chunk.logical_chunk_id, chunk.part_index, discriminator)
        ordinal = seen_discriminator.get(ordinal_key, 0)
        seen_discriminator[ordinal_key] = ordinal + 1
        if key not in seen_group:
            seen_group.add(key)
            continue
        new_logical_id = (
            f"chunk_{stable_hash(chunk.logical_chunk_id, discriminator, str(ordinal))}"
        )
        rewritten[index] = dataclasses.replace(
            chunk,
            logical_chunk_id=new_logical_id,
            chunk_version_id=chunk_version_id(
                new_logical_id,
                chunk.content_hash,
                parser_bundle_version,
                chunker_version,
            ),
        )

    return tuple(rewritten.get(index, chunk) for index, chunk in enumerate(chunks))
