"""Chunk size policy, token estimation, and content hashing (Blueprint §4.5.4).

Token counts are deterministic estimates (no external tokenizer dependency):
identifiers/words and standalone punctuation each count as one token. These are
starting values to be measured later (CLAUDE.md §7). The chunk content hash is a
pure SHA-256 over newline-normalized text — independent of line numbers, so a
chunk whose code is unchanged keeps its hash (and thus its version) even when
edits elsewhere shift its position.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"\w+|[^\s\w]")


def estimate_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def chunk_content_hash(raw_content: str) -> str:
    normalized = raw_content.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChunkSizePolicy:
    """Starting size guidance (Blueprint §4.5.4)."""

    target_min: int = 300
    target_max: int = 1200
    hard_max: int = 1800
    min_useful: int = 80
    overlap_pct: int = 15

    def is_oversized(self, token_count: int) -> bool:
        return token_count > self.hard_max


DEFAULT_POLICY = ChunkSizePolicy()
