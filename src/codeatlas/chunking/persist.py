"""Persist chunks into the Phase 2 chunk tables (Blueprint §10.10-10.12).

Maps :class:`Chunk` value objects to domain ``LogicalChunk`` / ``ChunkVersion``
and writes them through the coordinated writer. Chunk versions are content
addressed, so persisting identical content again reuses the existing row (no
duplication) — the basis for cross-snapshot artifact reuse (CLAUDE.md §2.6).
"""

from __future__ import annotations

from codeatlas.chunking.contracts import CHUNKER_VERSION, Chunk
from codeatlas.domain.entities import ChunkVersion, LogicalChunk
from codeatlas.storage.sqlite.repositories import ChunkStore
from codeatlas.storage.sqlite.writer import CoordinatedWriter


def chunk_to_logical(chunk: Chunk) -> LogicalChunk:
    return LogicalChunk(
        id=chunk.logical_chunk_id,
        repository_id=chunk.repository_id,
        normalized_path=chunk.normalized_path,
        chunk_role=chunk.chunk_role,
        qualified_name=chunk.qualified_name,
    )


def chunk_to_version(chunk: Chunk) -> ChunkVersion:
    return ChunkVersion(
        id=chunk.chunk_version_id,
        logical_chunk_id=chunk.logical_chunk_id,
        content_hash=chunk.content_hash,
        parser_version=chunk.parser_version,
        chunker_version=CHUNKER_VERSION,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        raw_content=chunk.raw_content,
        retrieval_content=chunk.retrieval_content,
    )


async def persist_chunks(writer: CoordinatedWriter, snapshot_id: str, chunks: list[Chunk]) -> None:
    """Persist chunks and attach them to ``snapshot_id`` (active membership)."""
    async with writer.transaction() as session:
        store = ChunkStore(session)
        for chunk in chunks:
            await store.upsert_logical(chunk_to_logical(chunk))
            await store.upsert_version(chunk_to_version(chunk))
            await store.add_membership(snapshot_id, chunk.chunk_version_id)
