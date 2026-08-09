"""Syntax-aware code chunking.

A chunk must be something a reader would recognize as a unit: a whole function,
a whole class outline, a whole file summary. Fixed-size splitting of raw bytes
is never the primary strategy, because a chunk that starts mid-statement
produces a citation nobody can check.

Two rules shape everything here:

* **Structure before size.** Boundaries come from parsed symbols. Size only
  decides whether an already-structural unit must be split further, and even
  then the split lands on statement boundaries.
* **Identity before content.** A chunk's logical ID depends on where it lives
  and what it is, never on its body. That is what allows an unchanged chunk to
  be copied into the next snapshot instead of recomputed, and it is why editing
  one symbol leaves every other chunk version byte-identical.

Container symbols — modules and classes — describe shape, so their retrieval
text names their members instead of repeating the members' bodies. Their content
hash covers that outline, so changing a method body does not invalidate the
class it lives in; adding or removing a member does.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from codeatlas.chunking.retrieval_text import (
    build_file_summary_text,
    build_symbol_retrieval_text,
)
from codeatlas.contracts import SymbolKind
from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.ids import chunk_version_id, logical_chunk_id
from codeatlas.domain.repository import FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.registry import PARSER_BUNDLE_VERSION

CHUNKER_VERSION: str = "1.1.0"
"""1.0.0 → 1.1.0 (ADR-0029): a container with no member symbols carries its
body rather than its declaration line, so an enum's values and docstring are
indexed. Chunk text and container identity change, which makes existing
snapshots stale; `indexing.py` refuses a stale chunker version rather than
mixing two chunking rules inside one snapshot."""

# Character budgets. Phase 2 has no tokenizer, so characters are a declared
# proxy at roughly four characters per token. A later phase may recalibrate
# these against a real tokenizer; changing them is a CHUNKER_VERSION bump.
TARGET_MIN_CHARACTERS = 1_200
TARGET_MAX_CHARACTERS = 4_800
HARD_MAX_CHARACTERS = 7_200
MIN_USEFUL_CHARACTERS = 320
OVERLAP_CHARACTERS = 720

# The smallest budget a split part may be given, so a pathological header can
# never reduce progress to zero lines per part.
_MINIMUM_PART_BUDGET = 500

_CONTAINER_KINDS = frozenset({SymbolKind.MODULE, SymbolKind.CLASS})


@dataclass(frozen=True)
class ChunkRequest:
    """Everything the chunker is allowed to know about one file."""

    repository_id: str
    file: FileRecord
    content: bytes
    symbols: tuple[SymbolRecord, ...]


class CodeChunker:
    """Turns one parsed file into its chunks. Pure: same input, same output."""

    version = CHUNKER_VERSION

    def chunk(self, request: ChunkRequest) -> tuple[LogicalChunk, ...]:
        text = request.content.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        if not lines:
            # An empty file has no line any chunk could cite (the parsers
            # emit no symbols for it either); a summary claiming line 1
            # would fail snapshot validation.
            return ()
        line_count = len(lines)

        ordered = sorted(
            request.symbols, key=lambda item: (item.start_line, item.qualified_name)
        )
        module = next(
            (item for item in ordered if item.kind is SymbolKind.MODULE), None
        )
        module_name = module.qualified_name if module is not None else ""
        children = _children_by_parent(ordered, module_name)

        chunks: list[LogicalChunk] = [
            self._file_summary(request, ordered, line_count)
        ]
        boundaries = _statement_lines(text)

        for symbol in ordered:
            chunks.extend(
                self._for_symbol(
                    request=request,
                    symbol=symbol,
                    lines=lines,
                    line_count=line_count,
                    members=children.get(symbol.qualified_name, ()),
                    module_name=module_name,
                    boundaries=boundaries,
                )
            )
        return tuple(chunks)

    def _file_summary(
        self,
        request: ChunkRequest,
        symbols: Sequence[SymbolRecord],
        line_count: int,
    ) -> LogicalChunk:
        exported = tuple(
            item.qualified_name
            for item in symbols
            if item.kind is not SymbolKind.MODULE
        )
        retrieval_text = build_file_summary_text(
            relative_path=request.file.relative_path,
            language=request.file.language,
            classification=request.file.classification,
            exported_symbols=exported,
            line_count=line_count,
        )
        # Hashed over the rendered metadata, so a summary is invalidated by a
        # change to what it actually claims and by nothing else.
        return self._build(
            request=request,
            role=ChunkRole.FILE_SUMMARY,
            qualified_name=request.file.relative_path,
            symbol_id=None,
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
        members: Sequence[SymbolRecord],
        module_name: str,
        boundaries: frozenset[int],
    ) -> tuple[LogicalChunk, ...]:
        start_line = max(symbol.start_line, 1)
        end_line = min(max(symbol.end_line, start_line), line_count)
        parent = _parent_name(symbol, module_name)

        # A container names its members instead of repeating their bodies,
        # because each member is chunked separately. With no members there is
        # no such separate chunk, and the outline reduces the symbol to its
        # declaration line — an enum indexed as `class OrderStatus(Enum):` and
        # nothing else, with its values and docstring absent from the index
        # entirely. A container with no members is a leaf, and leaves carry
        # their code.
        if symbol.kind in _CONTAINER_KINDS and members:
            return (
                self._container(
                    request=request,
                    symbol=symbol,
                    parent=parent,
                    members=members,
                    start_line=start_line,
                    end_line=end_line,
                    header=_definition_header(lines, start_line, end_line),
                ),
            )

        code = _slice(lines, start_line, end_line)
        whole = build_symbol_retrieval_text(
            relative_path=request.file.relative_path,
            language=request.file.language,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            parent=parent,
            signature=symbol.signature,
            docstring=None,
            start_line=start_line,
            end_line=end_line,
            code=code,
        )
        if len(whole) <= HARD_MAX_CHARACTERS:
            return (
                self._build(
                    request=request,
                    role=ChunkRole.SYMBOL,
                    qualified_name=symbol.qualified_name,
                    symbol_id=symbol.symbol_id,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=symbol.content_hash,
                    retrieval_text=whole,
                ),
            )

        return self._split(
            request=request,
            symbol=symbol,
            parent=parent,
            lines=lines,
            start_line=start_line,
            end_line=end_line,
            boundaries=boundaries,
        )

    def _container(
        self,
        *,
        request: ChunkRequest,
        symbol: SymbolRecord,
        parent: str | None,
        members: Sequence[SymbolRecord],
        start_line: int,
        end_line: int,
        header: str,
    ) -> LogicalChunk:
        member_names = tuple(item.qualified_name for item in members)
        retrieval_text = build_symbol_retrieval_text(
            relative_path=request.file.relative_path,
            language=request.file.language,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            parent=parent,
            signature=symbol.signature,
            docstring=None,
            start_line=start_line,
            end_line=end_line,
            code=header,
            members=member_names,
        )
        # A container is identified by its outline, not by its members' bodies.
        outline = "\n".join((symbol.qualified_name, header, *member_names))
        return self._build(
            request=request,
            role=ChunkRole.SYMBOL,
            qualified_name=symbol.qualified_name,
            symbol_id=symbol.symbol_id,
            start_line=start_line,
            end_line=end_line,
            content_hash=hash_text(outline),
            retrieval_text=retrieval_text,
        )

    def _split(
        self,
        *,
        request: ChunkRequest,
        symbol: SymbolRecord,
        parent: str | None,
        lines: Sequence[str],
        start_line: int,
        end_line: int,
        boundaries: frozenset[int],
    ) -> tuple[LogicalChunk, ...]:
        signature_line = _definition_header(lines, start_line, end_line)
        spans = split_line_spans(
            lines=lines,
            start_line=start_line,
            end_line=end_line,
            boundaries=boundaries,
            budget=_part_budget(
                relative_path=request.file.relative_path,
                language=request.file.language,
                symbol=symbol,
                parent=parent,
                start_line=start_line,
                end_line=end_line,
            ),
        )

        chunks: list[LogicalChunk] = []
        for index, (part_start, part_end) in enumerate(spans):
            code = _slice(lines, part_start, part_end)
            if index > 0:
                # Every part must stand alone as evidence, so it repeats the
                # definition it belongs to rather than starting mid-body.
                code = f"{signature_line}\n{code}"
            retrieval_text = build_symbol_retrieval_text(
                relative_path=request.file.relative_path,
                language=request.file.language,
                qualified_name=symbol.qualified_name,
                kind=symbol.kind,
                parent=parent,
                signature=symbol.signature,
                docstring=None,
                start_line=part_start,
                end_line=part_end,
                code=code,
                part_index=index,
                part_count=len(spans),
            )
            chunks.append(
                self._build(
                    request=request,
                    role=ChunkRole.SYMBOL_PART,
                    qualified_name=symbol.qualified_name,
                    symbol_id=symbol.symbol_id,
                    start_line=part_start,
                    end_line=part_end,
                    content_hash=hash_text(f"{symbol.content_hash}\x1f{index}\x1f{code}"),
                    retrieval_text=retrieval_text[:HARD_MAX_CHARACTERS],
                    part_index=index,
                    part_count=len(spans),
                )
            )
        return tuple(chunks)

    def _build(
        self,
        *,
        request: ChunkRequest,
        role: ChunkRole,
        qualified_name: str,
        symbol_id: str | None,
        start_line: int,
        end_line: int,
        content_hash: str,
        retrieval_text: str,
        part_index: int = 0,
        part_count: int = 1,
        heading_path: str = "",
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


def _children_by_parent(
    symbols: Sequence[SymbolRecord], module_name: str
) -> dict[str, tuple[SymbolRecord, ...]]:
    grouped: dict[str, list[SymbolRecord]] = {}
    for symbol in symbols:
        if symbol.kind is SymbolKind.MODULE:
            continue
        parent = _parent_name(symbol, module_name) or module_name
        grouped.setdefault(parent, []).append(symbol)
    return {name: tuple(items) for name, items in grouped.items()}


def _parent_name(symbol: SymbolRecord, module_name: str) -> str | None:
    """Return the qualified name of the symbol's immediate container."""
    if symbol.kind is SymbolKind.MODULE:
        return None
    if "." in symbol.qualified_name:
        return symbol.qualified_name.rsplit(".", 1)[0]
    return module_name or None


def _slice(lines: Sequence[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1 : end_line])


def _definition_header(lines: Sequence[str], start_line: int, end_line: int) -> str:
    """Return the definition's own header line, without its body.

    Used to give a container chunk and every split part something that names
    what they belong to. A multi-line signature is followed until the line that
    closes it, bounded so a pathological definition cannot pull in a body.
    """
    collected: list[str] = []
    # An empty file still parses to a module symbol claiming line 1, so the
    # range is clamped to the lines that exist rather than trusted.
    for offset in range(start_line, min(end_line, start_line + 20, len(lines)) + 1):
        line = lines[offset - 1]
        collected.append(line)
        if line.rstrip().endswith(":"):
            break
    return "\n".join(collected)


def _part_budget(
    *,
    relative_path: str,
    language: str,
    symbol: SymbolRecord,
    parent: str | None,
    start_line: int,
    end_line: int,
) -> int:
    """Characters of source a single part may carry.

    The header and the repeated signature are rendered for real rather than
    estimated, so the budget cannot drift from what is actually emitted.
    """
    header = build_symbol_retrieval_text(
        relative_path=relative_path,
        language=language,
        qualified_name=symbol.qualified_name,
        kind=symbol.kind,
        parent=parent,
        signature=symbol.signature,
        docstring=None,
        start_line=start_line,
        end_line=end_line,
        code="",
        part_index=0,
        part_count=2,
    )
    budget = HARD_MAX_CHARACTERS - len(header) - OVERLAP_CHARACTERS
    return max(budget, _MINIMUM_PART_BUDGET)


def split_line_spans(
    *,
    lines: Sequence[str],
    start_line: int,
    end_line: int,
    boundaries: frozenset[int],
    budget: int,
) -> tuple[tuple[int, int], ...]:
    """Cut [start_line, end_line] into line-aligned spans within the budget.

    A cut is placed at the last statement boundary that fits. If no boundary
    fits — a single statement larger than the budget — the cut falls on a line
    boundary instead, which still keeps evidence line-exact.
    """
    spans: list[tuple[int, int]] = []
    cursor = start_line
    while cursor <= end_line:
        used = 0
        last_boundary: int | None = None
        line = cursor
        while line <= end_line:
            used += len(lines[line - 1]) + 1
            if used > budget and line > cursor:
                break
            if line > cursor and line in boundaries:
                last_boundary = line
            line += 1

        if line > end_line:
            spans.append((cursor, end_line))
            break

        cut = (last_boundary - 1) if last_boundary is not None else (line - 1)
        cut = max(cut, cursor)
        spans.append((cursor, cut))
        cursor = _overlap_start(lines, cut + 1, cursor)

    if not spans:
        return ((start_line, end_line),)
    return tuple(spans)


def _overlap_start(lines: Sequence[str], next_line: int, floor_line: int) -> int:
    """Back up whole lines from ``next_line`` to create the overlap window."""
    accumulated = 0
    line = next_line
    while line - 1 > floor_line and accumulated < OVERLAP_CHARACTERS:
        accumulated += len(lines[line - 2]) + 1
        line -= 1
    return line


def _statement_lines(text: str) -> frozenset[int]:
    """Line numbers where a Python statement begins.

    Parsing is structural only: ``ast.parse`` never imports, executes, or
    resolves the source. When the file does not parse — the caller may still
    hold symbols recovered by Tree-sitter — every line counts as a boundary, so
    splitting degrades to line alignment instead of failing.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return frozenset(range(1, text.count("\n") + 2))
    return frozenset(
        node.lineno for node in ast.walk(tree) if isinstance(node, ast.stmt)
    )


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
