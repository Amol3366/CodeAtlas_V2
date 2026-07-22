"""Tree-sitter partial extraction for malformed Python (Blueprint §8.18).

When ``ast.parse`` fails, tree-sitter still produces a (partial) tree from which
we recover top-level and nested class/function symbols with exact line spans.
Symbols carry a reduced ``parser_confidence`` to signal the file did not parse
cleanly. No relations are emitted from partial trees (would be unreliable).
"""

from __future__ import annotations

from tree_sitter import Node

from codeatlas.domain.enums import Language, SymbolType
from codeatlas.domain.identity import symbol_id
from codeatlas.parsing.contracts import ParsedSymbol
from codeatlas.parsing.python.ast_extractor import module_qualified_name
from codeatlas.parsing.tree_sitter.loader import parse_python

_PARTIAL_CONFIDENCE = 0.7


def extract_partial(repository_id: str, relative_path: str, source: bytes) -> list[ParsedSymbol]:
    root = parse_python(source)
    module_qn = module_qualified_name(relative_path)
    module = ParsedSymbol(
        id=symbol_id(repository_id, relative_path, module_qn, SymbolType.MODULE),
        qualified_name=module_qn,
        short_name=module_qn.rsplit(".", 1)[-1],
        symbol_type=SymbolType.MODULE,
        language=Language.PYTHON,
        start_line=1,
        end_line=max(1, root.end_point.row + 1),
        parser_confidence=_PARTIAL_CONFIDENCE,
    )
    symbols = [module]
    _walk(root, repository_id, relative_path, qualifier="", parent_id=module.id, out=symbols)
    return symbols


def _walk(
    node: Node,
    repository_id: str,
    relative_path: str,
    *,
    qualifier: str,
    parent_id: str,
    out: list[ParsedSymbol],
) -> None:
    for child in node.children:
        if child.type in {"function_definition", "class_definition"}:
            name_node = child.child_by_field_name("name")
            if name_node is None or name_node.text is None:
                _walk(
                    child,
                    repository_id,
                    relative_path,
                    qualifier=qualifier,
                    parent_id=parent_id,
                    out=out,
                )
                continue
            name = name_node.text.decode("utf-8", errors="replace")
            qn = f"{qualifier}.{name}" if qualifier else name
            is_class = child.type == "class_definition"
            symbol_type = (
                SymbolType.CLASS
                if is_class
                else (SymbolType.METHOD if qualifier else SymbolType.FUNCTION)
            )
            symbol = ParsedSymbol(
                id=symbol_id(repository_id, relative_path, qn, symbol_type),
                qualified_name=qn,
                short_name=name,
                symbol_type=symbol_type,
                language=Language.PYTHON,
                start_line=child.start_point.row + 1,
                end_line=child.end_point.row + 1,
                parent_id=parent_id,
                exported=not name.startswith("_"),
                parser_confidence=_PARTIAL_CONFIDENCE,
            )
            out.append(symbol)
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(
                    body, repository_id, relative_path, qualifier=qn, parent_id=symbol.id, out=out
                )
        else:
            _walk(
                child,
                repository_id,
                relative_path,
                qualifier=qualifier,
                parent_id=parent_id,
                out=out,
            )
