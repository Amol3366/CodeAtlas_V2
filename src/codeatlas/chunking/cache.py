"""Chunk artifact cache (Blueprint §4.7.7).

Keyed by content hash + parser version + chunker version — all inputs that
affect the built artifact. Unchanged content is a cache hit, so re-chunking a
file that did not change reuses cached artifacts instead of recomputing them
(Phase 5 exit criterion). Process-local and in-memory; a durable cache can back
this later behind the same interface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")


class ChunkArtifactCache:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], object] = {}
        self.hits = 0
        self.misses = 0

    def get_or_compute(
        self,
        content_hash: str,
        parser_version: str,
        chunker_version: str,
        compute: Callable[[], _T],
    ) -> _T:
        key = (content_hash, parser_version, chunker_version)
        if key in self._store:
            self.hits += 1
            return self._store[key]  # type: ignore[return-value]
        self.misses += 1
        value = compute()
        self._store[key] = value
        return value
