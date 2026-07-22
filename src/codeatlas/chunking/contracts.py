"""Chunk value object and builder (Blueprint §4.5, §10.6).

A chunk stores ``raw_content`` (exact source, for citation) and
``retrieval_content`` (header + body, for search) separately. Identity is
content-addressed and line-independent:

    logical_chunk_id = f(repo, path, qualified_name, chunk_role)   # slot identity
    content_hash     = sha256(normalized raw_content)              # no line numbers
    chunk_version_id = f(logical_chunk_id, content_hash, parser_version, chunker_version)

Consequently, editing one symbol changes only that symbol's ``content_hash`` /
``chunk_version_id``; unrelated chunks keep their versions even though their line
numbers shift (CLAUDE.md §2.6, Phase 5 exit criteria).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from codeatlas.chunking.cache import ChunkArtifactCache
from codeatlas.chunking.token_budget import chunk_content_hash, estimate_tokens
from codeatlas.domain.enums import ChunkRole, Language
from codeatlas.domain.identity import chunk_version_id, logical_chunk_id

CHUNKER_VERSION = "0.1.0"


@dataclass(frozen=True)
class Chunk:
    """A single stable, content-addressed chunk."""

    logical_chunk_id: str
    chunk_version_id: str
    content_hash: str
    repository_id: str
    normalized_path: str
    chunk_role: ChunkRole
    parser_version: str
    start_line: int
    end_line: int
    raw_content: str
    retrieval_content: str
    token_count: int
    qualified_name: str | None = None
    symbol_id: str | None = None
    parent_chunk_id: str | None = None
    language: Language | None = None
    references: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def build_chunk(
    *,
    repository_id: str,
    normalized_path: str,
    qualified_name: str | None,
    chunk_role: ChunkRole,
    parser_version: str,
    start_line: int,
    end_line: int,
    raw_content: str,
    retrieval_content: str,
    language: Language | None = None,
    symbol_id: str | None = None,
    parent_chunk_id: str | None = None,
    references: Iterable[str] = (),
    metadata: Sequence[tuple[str, str]] = (),
    cache: ChunkArtifactCache | None = None,
) -> Chunk:
    content_hash = chunk_content_hash(raw_content)
    lcid = logical_chunk_id(repository_id, normalized_path, qualified_name, chunk_role)
    cvid = chunk_version_id(lcid, content_hash, parser_version, CHUNKER_VERSION)
    if cache is not None:
        token_count = cache.get_or_compute(
            content_hash, parser_version, CHUNKER_VERSION, lambda: estimate_tokens(raw_content)
        )
    else:
        token_count = estimate_tokens(raw_content)
    return Chunk(
        logical_chunk_id=lcid,
        chunk_version_id=cvid,
        content_hash=content_hash,
        repository_id=repository_id,
        normalized_path=normalized_path,
        chunk_role=chunk_role,
        parser_version=parser_version,
        start_line=start_line,
        end_line=end_line,
        raw_content=raw_content,
        retrieval_content=retrieval_content,
        token_count=token_count,
        qualified_name=qualified_name,
        symbol_id=symbol_id,
        parent_chunk_id=parent_chunk_id,
        language=language,
        references=tuple(references),
        metadata=tuple(metadata),
    )
