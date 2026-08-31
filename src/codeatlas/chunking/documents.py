"""Document and configuration chunking.

Prose has structure too. A Markdown heading and the body beneath it is the
document equivalent of a function: the unit a reader would cite. A top-level
configuration key is the same idea for JSON, YAML, and TOML.

Chunking here follows the document's own boundaries. An oversized section
splits at paragraph boundaries rather than mid-sentence, and every chunk keeps
its heading ancestry so a fragment can always be placed in context.
"""

from __future__ import annotations

from collections.abc import Sequence

from codeatlas.chunking.chunker import (
    CHUNKER_VERSION,
    HARD_MAX_CHARACTERS,
    OVERLAP_CHARACTERS,
    ChunkRequest,
    hash_text,
    split_line_spans,
)
from codeatlas.chunking.retrieval_text import (
    build_config_retrieval_text,
    build_document_retrieval_text,
    build_file_summary_text,
)
from codeatlas.contracts import SymbolKind
from codeatlas.domain.chunks import (
    ChunkRole,
    LogicalChunk,
    ensure_unique_chunk_ids,
)
from codeatlas.domain.ids import chunk_version_id, logical_chunk_id
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.registry import PARSER_BUNDLE_VERSION

_MINIMUM_PART_BUDGET = 500


class DocumentChunker:
    """Turns one parsed document into its chunks. Pure: same input, same output."""

    version = CHUNKER_VERSION

    def chunk(self, request: ChunkRequest) -> tuple[LogicalChunk, ...]:
        text = request.content.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        line_count = max(len(lines), 1)
        boundaries = _paragraph_lines(lines)

        ordered = sorted(
            request.symbols, key=lambda item: (item.start_line, item.qualified_name)
        )
        chunks: list[LogicalChunk] = [
            self._file_summary(request, ordered, line_count)
        ]
        for symbol in ordered:
            chunks.extend(
                self._for_symbol(
                    request=request,
                    symbol=symbol,
                    lines=lines,
                    line_count=line_count,
                    boundaries=boundaries,
                )
            )
        # After every chunk for this file exists, for the reason the
        # symbol pass runs before references: identity must be final
        # before anything downstream binds to it.
        return ensure_unique_chunk_ids(
            tuple(chunks), PARSER_BUNDLE_VERSION, CHUNKER_VERSION
        )

    def _file_summary(
        self,
        request: ChunkRequest,
        symbols: Sequence[SymbolRecord],
        line_count: int,
    ) -> LogicalChunk:
        retrieval_text = build_file_summary_text(
            relative_path=request.file.relative_path,
            language=request.file.language,
            classification=request.file.classification,
            exported_symbols=tuple(item.qualified_name for item in symbols),
            line_count=line_count,
        )
        return self._build(
            request=request,
            role=ChunkRole.FILE_SUMMARY,
            qualified_name=request.file.relative_path,
            symbol_id=None,
            heading_path="",
            start_line=1,
            end_line=line_count,
            content_hash=hash_text(retrieval_text),
            retrieval_text=retrieval_text,
        )

    def _for_symbol(
        self,
        *,
        request: ChunkRequest,
        symbol: SymbolRecord,
        lines: Sequence[str],
        line_count: int,
        boundaries: frozenset[int],
    ) -> tuple[LogicalChunk, ...]:
        role = (
            ChunkRole.CONFIG_KEY
            if symbol.kind is SymbolKind.CONFIG_KEY
            else ChunkRole.DOCUMENT_SECTION
        )
        start_line = max(symbol.start_line, 1)
        end_line = min(max(symbol.end_line, start_line), line_count)
        # The parser stores a document's structural context in `module_path`:
        # heading ancestry for a section, nested key paths for a config key.
        context = symbol.module_path

        if role is ChunkRole.CONFIG_KEY:
            retrieval_text = build_config_retrieval_text(
                relative_path=request.file.relative_path,
                language=request.file.language,
                key=symbol.qualified_name,
                nested_paths=tuple(
                    item for item in context.split(", ") if item
                ),
                start_line=start_line,
                end_line=end_line,
                body=_slice(lines, start_line, end_line),
            )
            return (
                self._build(
                    request=request,
                    role=role,
                    qualified_name=symbol.qualified_name,
                    symbol_id=symbol.symbol_id,
                    heading_path="",
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=symbol.content_hash,
                    retrieval_text=retrieval_text[:HARD_MAX_CHARACTERS],
                ),
            )

        spans = self._section_spans(
            request=request,
            symbol=symbol,
            heading_path=context,
            lines=lines,
            start_line=start_line,
            end_line=end_line,
            boundaries=boundaries,
        )
        chunks: list[LogicalChunk] = []
        for index, (part_start, part_end) in enumerate(spans):
            retrieval_text = build_document_retrieval_text(
                relative_path=request.file.relative_path,
                language=request.file.language,
                title=symbol.name,
                heading_path=context,
                start_line=part_start,
                end_line=part_end,
                body=_slice(lines, part_start, part_end),
                part_index=index,
                part_count=len(spans),
            )
            chunks.append(
                self._build(
                    request=request,
                    role=role,
                    qualified_name=symbol.qualified_name,
                    symbol_id=symbol.symbol_id,
                    heading_path=context,
                    start_line=part_start,
                    end_line=part_end,
                    content_hash=(
                        symbol.content_hash
                        if len(spans) == 1
                        else hash_text(f"{symbol.content_hash}\x1f{index}")
                    ),
                    retrieval_text=retrieval_text[:HARD_MAX_CHARACTERS],
                    part_index=index,
                    part_count=len(spans),
                )
            )
        return tuple(chunks)

    def _section_spans(
        self,
        *,
        request: ChunkRequest,
        symbol: SymbolRecord,
        heading_path: str,
        lines: Sequence[str],
        start_line: int,
        end_line: int,
        boundaries: frozenset[int],
    ) -> tuple[tuple[int, int], ...]:
        header = build_document_retrieval_text(
            relative_path=request.file.relative_path,
            language=request.file.language,
            title=symbol.name,
            heading_path=heading_path,
            start_line=start_line,
            end_line=end_line,
            body="",
            part_index=0,
            part_count=2,
        )
        whole = len(header) + len(_slice(lines, start_line, end_line))
        if whole <= HARD_MAX_CHARACTERS:
            return ((start_line, end_line),)

        budget = max(
            HARD_MAX_CHARACTERS - len(header) - OVERLAP_CHARACTERS,
            _MINIMUM_PART_BUDGET,
        )
        return split_line_spans(
            lines=lines,
            start_line=start_line,
            end_line=end_line,
            boundaries=boundaries,
            budget=budget,
        )

    def _build(
        self,
        *,
        request: ChunkRequest,
        role: ChunkRole,
        qualified_name: str,
        symbol_id: str | None,
        heading_path: str,
        start_line: int,
        end_line: int,
        content_hash: str,
        retrieval_text: str,
        part_index: int = 0,
        part_count: int = 1,
    ) -> LogicalChunk:
        logical = logical_chunk_id(
            request.repository_id,
            request.file.relative_path,
            qualified_name,
            role.value,
        )
        return LogicalChunk(
            logical_chunk_id=logical,
            chunk_version_id=chunk_version_id(
                logical,
                hash_text(f"{content_hash}\x1f{part_index}"),
                PARSER_BUNDLE_VERSION,
                self.version,
            ),
            file_id=request.file.file_id,
            symbol_id=symbol_id,
            role=role,
            qualified_name=qualified_name,
            heading_path=heading_path,
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash,
            retrieval_text=retrieval_text,
            part_index=part_index,
            part_count=part_count,
        )


def _paragraph_lines(lines: Sequence[str]) -> frozenset[int]:
    """Lines that begin a paragraph — the split points for a long section."""
    starts = {1}
    previous_blank = True
    for offset, line in enumerate(lines, start=1):
        blank = not line.strip()
        if previous_blank and not blank:
            starts.add(offset)
        previous_blank = blank
    return frozenset(starts)


def _slice(lines: Sequence[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1 : end_line])
