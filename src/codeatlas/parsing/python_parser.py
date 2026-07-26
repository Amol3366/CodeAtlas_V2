"""Python symbol extraction.

Two layers run for every file, each doing what it is best at:

* ``ast`` is authoritative for structure — qualified names, decorators, async
  definitions, docstrings, and exact line ranges. It parses only; nothing is
  imported, compiled for execution, or evaluated.
* Tree-sitter supplies byte spans for definitions and, when ``ast`` rejects the
  file outright, recovers whatever symbols it can from the error-tolerant tree so
  a malformed file still contributes what it legitimately declares.

A definition's range starts at its first decorator when it has any, because the
decorator is part of what defines the symbol's behavior and a reader asking
"where is this defined" expects to see it.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from typing import Final

from tree_sitter import Language, Node, Parser
from tree_sitter_python import language as python_language

from codeatlas.contracts import SymbolKind
from codeatlas.domain.ids import symbol_id, symbol_version_id
from codeatlas.domain.repository import FileClassification
from codeatlas.domain.symbols import SymbolRecord, Visibility
from codeatlas.extraction.python_relations import extract_python_references
from codeatlas.parsing.registry import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)
from codeatlas.repositories.classification import classify

MAX_PARSE_BYTES: Final[int] = 2_000_000
_UTF8_BOM: Final[bytes] = b"\xef\xbb\xbf"

_DEFINITION_NODE_TYPES: Final[frozenset[str]] = frozenset(
    {"class_definition", "function_definition", "decorated_definition"}
)


@dataclass(frozen=True)
class _Span:
    start_byte: int
    end_byte: int


class PythonParser:
    """Extracts Python symbols without executing repository code."""

    name = "python"
    version = PARSER_BUNDLE_VERSION
    supported_languages = frozenset({"python"})

    def __init__(self) -> None:
        self._parser = Parser(Language(python_language()))

    def parse(self, request: ParseRequest) -> ParseResult:
        """Parse one Python file into symbols and diagnostics."""
        if len(request.content) > MAX_PARSE_BYTES:
            return self._failed(
                ParseDiagnostic(
                    code="PARSE_TOO_LARGE",
                    message="The file exceeds the maximum parsable size.",
                )
            )

        # Windows tooling routinely writes UTF-8 with a byte-order mark. It is
        # stripped before parsing (a BOM is a syntax error to `ast`), and the
        # byte length it occupied is added back to every span so offsets still
        # index the original file content.
        bom_length = len(_UTF8_BOM) if request.content.startswith(_UTF8_BOM) else 0
        body = request.content[bom_length:]

        try:
            source = body.decode("utf-8")
        except UnicodeDecodeError:
            return self._failed(
                ParseDiagnostic(
                    code="PARSE_DECODE_ERROR",
                    message="The file is not valid UTF-8 text.",
                )
            )

        tree = self._parser.parse(body)
        spans = _index_definition_spans(tree.root_node, bom_length)
        line_offsets = _line_offsets(body, bom_length)
        module_path = _module_path(request.relative_path)
        is_test_file = (
            classify(request.relative_path)[0] is FileClassification.TEST_CODE
        )

        try:
            module = ast.parse(source)
        except SyntaxError as error:
            recovered = _recover_symbols(
                root=tree.root_node,
                request=request,
                module_path=module_path,
                is_test_file=is_test_file,
                base_offset=bom_length,
            )
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                symbols=recovered,
                diagnostics=(
                    ParseDiagnostic(
                        code="PARSE_SYNTAX_ERROR",
                        message="The file could not be parsed as Python.",
                        start_line=error.lineno,
                    ),
                ),
            )

        symbols: list[SymbolRecord] = [
            _build_symbol(
                request=request,
                kind=SymbolKind.MODULE,
                name=module_path.rsplit(".", 1)[-1],
                qualified_name=module_path,
                module_path=module_path,
                signature=None,
                start_line=1,
                end_line=max(len(line_offsets), 1),
                span=_Span(0, len(request.content)),
            )
        ]
        symbols.extend(
            _collect(
                body=module.body,
                prefix="",
                inside_class=False,
                request=request,
                module_path=module_path,
                spans=spans,
                line_offsets=line_offsets,
                is_test_file=is_test_file,
            )
        )

        # Extraction reuses the module `ast` already produced: one parse, not two.
        extraction = extract_python_references(
            module=module,
            module_path=module_path,
            file_id=request.file_id,
            symbol_ids={
                symbol.qualified_name: symbol.symbol_id for symbol in symbols
            },
        )

        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            symbols=tuple(symbols),
            diagnostics=extraction.diagnostics,
            references=extraction.references,
        )

    def _failed(self, diagnostic: ParseDiagnostic) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=False,
            symbols=(),
            diagnostics=(diagnostic,),
        )


def _collect(
    *,
    body: list[ast.stmt],
    prefix: str,
    inside_class: bool,
    request: ParseRequest,
    module_path: str,
    spans: dict[int, _Span],
    line_offsets: list[int],
    is_test_file: bool,
) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []

    for node in body:
        if isinstance(node, ast.ClassDef):
            qualified_name = f"{prefix}{node.name}"
            start_line = _definition_start_line(node)
            symbols.append(
                _build_symbol(
                    request=request,
                    kind=SymbolKind.CLASS,
                    name=node.name,
                    qualified_name=qualified_name,
                    module_path=module_path,
                    signature=None,
                    start_line=start_line,
                    end_line=node.end_lineno or start_line,
                    span=_span_for(
                        spans=spans,
                        start_line=start_line,
                        end_line=node.end_lineno or start_line,
                        line_offsets=line_offsets,
                        node=node,
                    ),
                )
            )
            symbols.extend(
                _collect(
                    body=node.body,
                    prefix=f"{qualified_name}.",
                    inside_class=True,
                    request=request,
                    module_path=module_path,
                    spans=spans,
                    line_offsets=line_offsets,
                    is_test_file=is_test_file,
                )
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            qualified_name = f"{prefix}{node.name}"
            start_line = _definition_start_line(node)
            symbols.append(
                _build_symbol(
                    request=request,
                    kind=_function_kind(
                        node.name, inside_class=inside_class, is_test_file=is_test_file
                    ),
                    name=node.name,
                    qualified_name=qualified_name,
                    module_path=module_path,
                    signature=_signature(node),
                    start_line=start_line,
                    end_line=node.end_lineno or start_line,
                    span=_span_for(
                        spans=spans,
                        start_line=start_line,
                        end_line=node.end_lineno or start_line,
                        line_offsets=line_offsets,
                        node=node,
                    ),
                )
            )
            symbols.extend(
                _collect(
                    body=node.body,
                    prefix=f"{qualified_name}.",
                    inside_class=False,
                    request=request,
                    module_path=module_path,
                    spans=spans,
                    line_offsets=line_offsets,
                    is_test_file=is_test_file,
                )
            )
        elif not inside_class and prefix == "":
            constant = _module_constant(node)
            if constant is not None:
                name, start_line, end_line = constant
                symbols.append(
                    _build_symbol(
                        request=request,
                        kind=SymbolKind.CONSTANT,
                        name=name,
                        qualified_name=name,
                        module_path=module_path,
                        signature=None,
                        start_line=start_line,
                        end_line=end_line,
                        span=_line_span(line_offsets, start_line, end_line, node),
                    )
                )

    return symbols


def _build_symbol(
    *,
    request: ParseRequest,
    kind: SymbolKind,
    name: str,
    qualified_name: str,
    module_path: str,
    signature: str | None,
    start_line: int,
    end_line: int,
    span: _Span,
) -> SymbolRecord:
    definition_bytes = request.content[span.start_byte : span.end_byte]
    content_hash = hashlib.sha256(definition_bytes).hexdigest()
    logical_id = symbol_id(
        request.repository_id, request.relative_path, qualified_name, kind.value
    )
    return SymbolRecord(
        symbol_id=logical_id,
        symbol_version_id=symbol_version_id(
            logical_id, content_hash, PARSER_BUNDLE_VERSION
        ),
        file_id=request.file_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        module_path=module_path,
        signature=signature,
        start_line=start_line,
        end_line=end_line,
        start_byte=span.start_byte,
        end_byte=span.end_byte,
        content_hash=content_hash,
        visibility=_visibility(qualified_name),
    )


def _function_kind(
    name: str, *, inside_class: bool, is_test_file: bool
) -> SymbolKind:
    if inside_class:
        return SymbolKind.CONSTRUCTOR if name == "__init__" else SymbolKind.METHOD
    if is_test_file and name.startswith("test_"):
        return SymbolKind.TEST
    return SymbolKind.FUNCTION


def _definition_start_line(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> int:
    if node.decorator_list:
        # `lineno` of a decorator points at the expression after "@", which is on
        # the same line as the "@" itself.
        return min(decorator.lineno for decorator in node.decorator_list)
    return node.lineno


def _module_constant(node: ast.stmt) -> tuple[str, int, int] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and _is_constant_name(target.id):
            return target.id, node.lineno, node.end_lineno or node.lineno
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and _is_constant_name(node.target.id)
    ):
        return node.target.id, node.lineno, node.end_lineno or node.lineno
    return None


def _is_constant_name(name: str) -> bool:
    stripped = name.lstrip("_")
    return bool(stripped) and stripped.upper() == stripped and not stripped.isdigit()


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    try:
        arguments = ast.unparse(node.args)
    except (AttributeError, ValueError):
        return None
    returns = ""
    if node.returns is not None:
        try:
            returns = f" -> {ast.unparse(node.returns)}"
        except (AttributeError, ValueError):
            returns = ""
    return f"({arguments}){returns}"


def _visibility(qualified_name: str) -> Visibility:
    return (
        "private"
        if any(part.startswith("_") for part in qualified_name.split("."))
        else "public"
    )


def _module_path(relative_path: str) -> str:
    without_suffix = relative_path.rsplit(".", 1)[0]
    dotted = without_suffix.replace("/", ".")
    if dotted.endswith(".__init__"):
        return dotted[: -len(".__init__")]
    return dotted


def _line_offsets(content: bytes, base_offset: int = 0) -> list[int]:
    offsets = [base_offset]
    for index, byte in enumerate(content):
        if byte == 0x0A and index + 1 < len(content):
            offsets.append(base_offset + index + 1)
    return offsets


def _index_definition_spans(root: Node, base_offset: int = 0) -> dict[int, _Span]:
    """Map a 1-based start row to the widest definition span starting there."""
    spans: dict[int, _Span] = {}
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        if node.type in _DEFINITION_NODE_TYPES:
            row = node.start_point[0] + 1
            candidate = _Span(
                node.start_byte + base_offset, node.end_byte + base_offset
            )
            existing = spans.get(row)
            width = candidate.end_byte - candidate.start_byte
            if existing is None or width > existing.end_byte - existing.start_byte:
                spans[row] = candidate
        stack.extend(node.children)
    return spans


def _span_for(
    *,
    spans: dict[int, _Span],
    start_line: int,
    end_line: int,
    line_offsets: list[int],
    node: ast.AST,
) -> _Span:
    span = spans.get(start_line)
    if span is not None:
        return span
    return _line_span(line_offsets, start_line, end_line, node)


def _line_span(
    line_offsets: list[int], start_line: int, end_line: int, node: ast.AST
) -> _Span:
    start_index = min(max(start_line - 1, 0), len(line_offsets) - 1)
    end_index = min(max(end_line - 1, 0), len(line_offsets) - 1)
    start_byte = line_offsets[start_index]
    end_column = getattr(node, "end_col_offset", None)
    end_byte = line_offsets[end_index] + (end_column if end_column is not None else 0)
    return _Span(start_byte, max(end_byte, start_byte))


def _recover_symbols(
    *,
    root: Node,
    request: ParseRequest,
    module_path: str,
    is_test_file: bool,
    base_offset: int = 0,
) -> tuple[SymbolRecord, ...]:
    """Extract what the error-tolerant tree can still identify."""
    symbols: list[SymbolRecord] = []

    def visit(node: Node, prefix: str, inside_class: bool) -> None:
        for child in node.children:
            if child.type not in {"class_definition", "function_definition"}:
                visit(child, prefix, inside_class)
                continue

            name_node = child.child_by_field_name("name")
            if name_node is None or name_node.text is None:
                continue
            name = name_node.text.decode("utf-8", errors="replace")
            qualified_name = f"{prefix}{name}"
            is_class = child.type == "class_definition"
            kind = (
                SymbolKind.CLASS
                if is_class
                else _function_kind(
                    name, inside_class=inside_class, is_test_file=is_test_file
                )
            )
            symbols.append(
                _build_symbol(
                    request=request,
                    kind=kind,
                    name=name,
                    qualified_name=qualified_name,
                    module_path=module_path,
                    signature=None,
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    span=_Span(
                        child.start_byte + base_offset,
                        child.end_byte + base_offset,
                    ),
                )
            )
            body = child.child_by_field_name("body")
            if body is not None:
                visit(body, f"{qualified_name}.", is_class)

    visit(root, "", False)
    return tuple(symbols)
