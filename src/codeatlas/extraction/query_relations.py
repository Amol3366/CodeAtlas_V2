"""Turns query captures into SymbolReferences.

A reference is what the file *said*. Nothing is resolved here: resolution needs
the whole snapshot and happens later, which is what lets an unchanged file's
references be reused verbatim.

A ``tags.scm`` ``reference.call`` is a pattern match with **no receiver
context**, where ``python_relations.py`` walks a real ``ast`` and knows what a
call was invoked on. That is strictly less information, and it is why ADR-0065
declares that query-backed languages resolve calls less completely than Python
does. An edge that cannot be established stays unresolved; it is never invented.
"""

from __future__ import annotations

from typing import Any

from tree_sitter import QueryCursor

from codeatlas.contracts import RelationKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.query_backed.profile import LanguageAdapter
from codeatlas.parsing.registry import ParseRequest

_KIND_BY_CAPTURE = {
    "reference.call": RelationKind.CALLS,
    "reference.implementation": RelationKind.IMPLEMENTS,
    "reference.class": RelationKind.REFERENCES,
    "reference.type": RelationKind.REFERENCES,
    "reference.interface": RelationKind.REFERENCES,
}


def extract_query_references(
    root: Any,
    source: bytes,
    request: ParseRequest,
    adapter: LanguageAdapter,
    symbols: tuple[SymbolRecord, ...],
) -> tuple[SymbolReference, ...]:
    """Every reference this file states, attributed to its enclosing symbol."""
    module_symbol_id = symbols[0].symbol_id if symbols else f"module_{request.file_id}"
    references = list(adapter.imports(root, source, request.file_id, module_symbol_id))
    parts: dict[tuple[str, RelationKind, str, int], int] = {}
    # The grammar's shipped query, then this repository's supplementary one
    # when a language has it (ADR-0067). Both use the same
    # `reference.*` / `@name` convention, so one loop consumes both and
    # neither needs to know the other exists.
    #
    # `parts` spans both deliberately: a name captured by both queries on
    # one line is the same call, and giving the second occurrence a distinct
    # `part` would store one call twice.
    queries = [adapter.profile.tags_query]
    if adapter.profile.references_query is not None:
        queries.append(adapter.profile.references_query)
    for query in queries:
        for _pattern, captures in QueryCursor(query).matches(root):
            kind = _match_kind(captures)
            if kind is None:
                continue
            # The reference capture marks the *kind*; the target name is a separate
            # `@name` capture in the same match. Java's tags.scm puts
            # `@reference.call` on the argument list, not the method name, so
            # reading the reference node's own text yields "(orderId)" rather than
            # "charge" -- and `implements A, B` would yield "A, B".
            for name_node in captures.get("name", ()):
                hint = _text(name_node, source)
                line = name_node.start_point[0] + 1
                owner = _enclosing_symbol_id(line, symbols, module_symbol_id)
                # `part` distinguishes two otherwise-identical references on one
                # line, as in `f(f(x))`. Both are real edges.
                key = (owner, kind, hint, line)
                part = parts.get(key, 0)
                parts[key] = part + 1
                references.append(
                    SymbolReference(
                        source_symbol_id=owner,
                        file_id=request.file_id,
                        kind=kind,
                        target_hint=hint,
                        module_hint="",
                        start_line=line,
                        end_line=name_node.end_point[0] + 1,
                        part=part,
                    )
                )
    return tuple(references)


def _match_kind(captures: dict[str, Any]) -> RelationKind | None:
    """The relation kind this match declares, if it declares one."""
    for capture_name, nodes in captures.items():
        if nodes and capture_name in _KIND_BY_CAPTURE:
            return _KIND_BY_CAPTURE[capture_name]
    return None


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _enclosing_symbol_id(
    line: int, symbols: tuple[SymbolRecord, ...], fallback: str
) -> str:
    """The innermost symbol whose range covers this line."""
    best: SymbolRecord | None = None
    for symbol in symbols:
        if symbol.start_line <= line <= symbol.end_line and (
            best is None or symbol.start_line > best.start_line
        ):
            best = symbol
    return best.symbol_id if best is not None else fallback
