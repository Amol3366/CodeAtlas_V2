"""Lexical search hits.

A hit is a *candidate*, not a conclusion. It records where the match was found
and how it ranked, and nothing about what the match means. Turning a candidate
into a claim — with a derivation label and validated evidence — happens in the
application layer, where the snapshot and the file on disk can both be checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from codeatlas.domain.chunks import ChunkRole


@dataclass(frozen=True)
class ChunkSearchHit:
    """One chunk that matched, with the location needed to cite it."""

    logical_chunk_id: str
    part_index: int
    file_id: str
    relative_path: str
    qualified_name: str
    role: ChunkRole
    symbol_id: str | None
    start_line: int
    end_line: int
    rank: float


@dataclass(frozen=True)
class FileSearchHit:
    """One file whose path matched."""

    file_id: str
    relative_path: str
    rank: float
