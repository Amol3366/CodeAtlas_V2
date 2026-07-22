"""Syntax-aware code chunker (Blueprint §4.5).

Turns a :class:`ParseResult` + source into stable chunks:
- one FILE_SUMMARY chunk (deterministic metadata; no LLM);
- one SYMBOL_IMPLEMENTATION chunk per function/method/class/etc. (a class chunk
  covers only its header — signature/docstring/leading fields — so editing a
  method never invalidates the class chunk);
- OVERSIZED_SYMBOL_PART chunks when a symbol exceeds the hard token cap;
- CALL_SITE chunks around calls, identified by call occurrence (line-independent).
"""

from __future__ import annotations

from collections import defaultdict

from codeatlas.chunking.cache import ChunkArtifactCache
from codeatlas.chunking.contracts import Chunk, build_chunk
from codeatlas.chunking.oversized_symbol import partition_by_tokens
from codeatlas.chunking.token_budget import DEFAULT_POLICY, ChunkSizePolicy, estimate_tokens
from codeatlas.domain.enums import ChunkRole, Language, RelationType, SymbolType
from codeatlas.parsing.contracts import ParsedSymbol, ParseResult

_CLASS_LIKE = frozenset({SymbolType.CLASS})
_METHOD_LIKE = frozenset({SymbolType.METHOD, SymbolType.CONSTRUCTOR})
_CALL_CONTEXT_LINES = 2


def _lang(language: Language | None) -> str:
    return language.value if language is not None else "unknown"


def _slice(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


class CodeChunker:
    def __init__(self, policy: ChunkSizePolicy = DEFAULT_POLICY) -> None:
        self._policy = policy

    def chunk(
        self,
        parse_result: ParseResult,
        source: str,
        repository_id: str,
        *,
        cache: ChunkArtifactCache | None = None,
    ) -> list[Chunk]:
        path = parse_result.relative_path
        language = parse_result.language
        parser_version = parse_result.parser_version
        lines = source.splitlines(keepends=True)
        symbols = list(parse_result.symbols)
        by_id = {s.id: s for s in symbols}
        children: dict[str, list[ParsedSymbol]] = defaultdict(list)
        for symbol in symbols:
            if symbol.parent_id is not None:
                children[symbol.parent_id].append(symbol)
        imports = sorted(
            {
                r.target_name
                for r in parse_result.relations
                if r.relation_type is RelationType.IMPORTS
            }
        )

        chunks: list[Chunk] = [
            self._file_summary(parse_result, repository_id, symbols, imports, cache)
        ]
        for symbol in symbols:
            if symbol.symbol_type is SymbolType.MODULE:
                continue
            start, end = self._span(symbol, children)
            if end < start:
                continue
            raw = _slice(lines, start, end)
            if not raw.strip():
                continue
            parent_qn = self._parent_qn(symbol, by_id)
            if self._policy.is_oversized(estimate_tokens(raw)):
                chunks.extend(
                    self._oversized(
                        symbol,
                        lines,
                        start,
                        end,
                        path,
                        language,
                        parser_version,
                        imports,
                        parent_qn,
                        repository_id,
                        cache,
                    )
                )
            else:
                chunks.append(
                    self._symbol_chunk(
                        symbol,
                        raw,
                        start,
                        end,
                        path,
                        language,
                        parser_version,
                        imports,
                        parent_qn,
                        repository_id,
                        cache,
                    )
                )
        chunks.extend(
            self._call_sites(parse_result, lines, path, language, repository_id, by_id, cache)
        )
        return chunks

    # --- Span selection ------------------------------------------------------

    def _span(
        self, symbol: ParsedSymbol, children: dict[str, list[ParsedSymbol]]
    ) -> tuple[int, int]:
        if symbol.symbol_type in _CLASS_LIKE:
            method_starts = [
                child.start_line
                for child in children.get(symbol.id, [])
                if child.symbol_type in _METHOD_LIKE
            ]
            if method_starts:
                return symbol.start_line, max(symbol.start_line, min(method_starts) - 1)
        return symbol.start_line, symbol.end_line

    def _parent_qn(self, symbol: ParsedSymbol, by_id: dict[str, ParsedSymbol]) -> str | None:
        if symbol.parent_id is None:
            return None
        parent = by_id.get(symbol.parent_id)
        if parent is None or parent.symbol_type is SymbolType.MODULE:
            return None
        return parent.qualified_name

    # --- Chunk builders ------------------------------------------------------

    def _file_summary(
        self,
        parse_result: ParseResult,
        repository_id: str,
        symbols: list[ParsedSymbol],
        imports: list[str],
        cache: ChunkArtifactCache | None,
    ) -> Chunk:
        exported = sorted(
            s.qualified_name
            for s in symbols
            if s.exported and s.symbol_type is not SymbolType.MODULE
        )
        summary_lines = [
            f"PATH: {parse_result.relative_path}",
            f"LANGUAGE: {_lang(parse_result.language)}",
            f"SYMBOLS: {len([s for s in symbols if s.symbol_type is not SymbolType.MODULE])}",
            f"EXPORTS: {', '.join(exported)}",
            f"IMPORTS: {', '.join(imports)}",
        ]
        raw = "\n".join(summary_lines)
        return build_chunk(
            repository_id=repository_id,
            normalized_path=parse_result.relative_path,
            qualified_name=None,
            chunk_role=ChunkRole.FILE_SUMMARY,
            parser_version=parse_result.parser_version,
            start_line=1,
            end_line=max(1, len(symbols)),
            raw_content=raw,
            retrieval_content="FILE SUMMARY\n" + raw,
            language=parse_result.language,
            cache=cache,
        )

    def _symbol_chunk(
        self,
        symbol: ParsedSymbol,
        raw: str,
        start: int,
        end: int,
        path: str,
        language: Language | None,
        parser_version: str,
        imports: list[str],
        parent_qn: str | None,
        repository_id: str,
        cache: ChunkArtifactCache | None,
    ) -> Chunk:
        retrieval = _symbol_header(path, language, symbol, parent_qn, imports, start, end) + raw
        return build_chunk(
            repository_id=repository_id,
            normalized_path=path,
            qualified_name=symbol.qualified_name,
            chunk_role=ChunkRole.SYMBOL_IMPLEMENTATION,
            parser_version=parser_version,
            start_line=start,
            end_line=end,
            raw_content=raw,
            retrieval_content=retrieval,
            language=language,
            symbol_id=symbol.id,
            references=(symbol.qualified_name,),
            cache=cache,
        )

    def _oversized(
        self,
        symbol: ParsedSymbol,
        lines: list[str],
        start: int,
        end: int,
        path: str,
        language: Language | None,
        parser_version: str,
        imports: list[str],
        parent_qn: str | None,
        repository_id: str,
        cache: ChunkArtifactCache | None,
    ) -> list[Chunk]:
        parts = partition_by_tokens(lines, start, end, self._policy.target_max)
        chunks: list[Chunk] = []
        for index, (part_start, part_end) in enumerate(parts):
            raw = _slice(lines, part_start, part_end)
            qn = f"{symbol.qualified_name}#part{index}"
            header = _oversized_header(
                path, language, symbol, parent_qn, part_start, part_end, index
            )
            chunks.append(
                build_chunk(
                    repository_id=repository_id,
                    normalized_path=path,
                    qualified_name=qn,
                    chunk_role=ChunkRole.OVERSIZED_SYMBOL_PART,
                    parser_version=parser_version,
                    start_line=part_start,
                    end_line=part_end,
                    raw_content=raw,
                    retrieval_content=header + raw,
                    language=language,
                    symbol_id=symbol.id,
                    metadata=(("part_index", str(index)), ("part_count", str(len(parts)))),
                    cache=cache,
                )
            )
        return chunks

    def _call_sites(
        self,
        parse_result: ParseResult,
        lines: list[str],
        path: str,
        language: Language | None,
        repository_id: str,
        by_id: dict[str, ParsedSymbol],
        cache: ChunkArtifactCache | None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        occurrences: dict[tuple[str, str], int] = defaultdict(int)
        for relation in parse_result.relations:
            if relation.relation_type not in (RelationType.CALLS, RelationType.MAY_CALL):
                continue
            source = by_id.get(relation.source_id)
            if source is None:
                continue
            line = relation.evidence_start_line
            if line < 1 or line > len(lines):
                continue
            key = (relation.source_id, relation.target_name)
            occurrence = occurrences[key]
            occurrences[key] += 1
            start = max(1, line - _CALL_CONTEXT_LINES)
            end = min(len(lines), line + _CALL_CONTEXT_LINES)
            raw = _slice(lines, start, end)
            qn = f"{source.qualified_name}->{relation.target_name}#{occurrence}"
            header = (
                f"PATH: {path}\nLANGUAGE: {_lang(language)}\n"
                f"CALL SITE: {source.qualified_name} {relation.relation_type.value} "
                f"{relation.target_name}\nLINES: {start}-{end}\n\nCODE:\n"
            )
            chunks.append(
                build_chunk(
                    repository_id=repository_id,
                    normalized_path=path,
                    qualified_name=qn,
                    chunk_role=ChunkRole.CALL_SITE,
                    parser_version=parse_result.parser_version,
                    start_line=start,
                    end_line=end,
                    raw_content=raw,
                    retrieval_content=header + raw,
                    language=language,
                    symbol_id=source.id,
                    references=(relation.target_name,),
                    cache=cache,
                )
            )
        return chunks


def _symbol_header(
    path: str,
    language: Language | None,
    symbol: ParsedSymbol,
    parent_qn: str | None,
    imports: list[str],
    start: int,
    end: int,
) -> str:
    header = [
        f"PATH: {path}",
        f"LANGUAGE: {_lang(language)}",
        f"SYMBOL: {symbol.qualified_name}",
        f"TYPE: {symbol.symbol_type.value}",
    ]
    if parent_qn is not None:
        header.append(f"PARENT: {parent_qn}")
    header.append(f"LINES: {start}-{end}")
    if imports:
        header.append(f"IMPORTS: {', '.join(imports[:12])}")
    if symbol.signature:
        header.append(f"SIGNATURE: {symbol.signature}")
    if symbol.docstring:
        header.append(f"DOCSTRING: {symbol.docstring.strip().splitlines()[0]}")
    return "\n".join(header) + "\n\nCODE:\n"


def _oversized_header(
    path: str,
    language: Language | None,
    symbol: ParsedSymbol,
    parent_qn: str | None,
    start: int,
    end: int,
    index: int,
) -> str:
    header = [
        f"PATH: {path}",
        f"LANGUAGE: {_lang(language)}",
        f"SYMBOL: {symbol.qualified_name} (part {index})",
        f"TYPE: {symbol.symbol_type.value}",
    ]
    if parent_qn is not None:
        header.append(f"PARENT: {parent_qn}")
    if symbol.signature:
        header.append(f"SIGNATURE: {symbol.signature}")
    header.append(f"LINES: {start}-{end}")
    return "\n".join(header) + "\n\nCODE:\n"
