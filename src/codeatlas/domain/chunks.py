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

from dataclasses import dataclass
from enum import StrEnum


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
