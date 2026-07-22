"""Oversized-symbol splitting (Blueprint §4.5.3).

A symbol larger than the hard token cap is split into contiguous line-aligned
parts. Splitting on line boundaries guarantees exact, unbroken line mapping: the
parts partition ``[start, end]`` with no gaps or overlaps (Phase 5 property).
The parent signature is preserved in each part's retrieval header (limited
overlap at the retrieval layer, not in ``raw_content``).
"""

from __future__ import annotations

from codeatlas.chunking.token_budget import estimate_tokens


def partition_by_tokens(
    lines: list[str], start: int, end: int, target_tokens: int
) -> list[tuple[int, int]]:
    """Partition inclusive line range [start, end] into contiguous token-sized windows."""
    parts: list[tuple[int, int]] = []
    current_start = start
    accumulated = 0
    for line_no in range(start, end + 1):
        accumulated += estimate_tokens(lines[line_no - 1])
        if accumulated >= target_tokens and line_no < end:
            parts.append((current_start, line_no))
            current_start = line_no + 1
            accumulated = 0
    parts.append((current_start, end))
    return parts
