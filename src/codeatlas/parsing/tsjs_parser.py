"""TypeScript and JavaScript symbol extraction.

Tree-sitter is authoritative here for both structure and spans. Python gets a
second opinion from ``ast``; TypeScript has no in-process equivalent, and running
``tsc`` would execute repository tooling, which ``CLAUDE.md`` Section 4.4
forbids. That is a genuine accuracy difference between the two languages and is
declared as a limitation rather than papered over: what Tree-sitter cannot see —
inferred types, resolved module graphs, declaration merging — this parser does
not claim to know.

Nothing is imported, transpiled, type-checked, or resolved through a package
manager. A module specifier is untrusted text; it is recorded, never followed.

An exported declaration's range starts at the ``export`` keyword, for the same
reason the Python parser's ranges start at the first decorator: it is part of
what defines the symbol, and a reader asking "where is this defined" expects to
see it.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import replace
from typing import Final

from tree_sitter import Language, Node, Parser
from tree_sitter_javascript import language as javascript_language
from tree_sitter_typescript import language_tsx, language_typescript

from codeatlas.contracts import SymbolKind
from codeatlas.domain.ids import symbol_id, symbol_version_id
from codeatlas.domain.symbols import SymbolRecord, Visibility
from codeatlas.extraction.tsjs_relations import extract_tsjs_references
from codeatlas.parsing.registry import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)

# Matches the Python parser's limit. Each parser owns its own bound so a change
# for one language cannot silently widen another.
MAX_PARSE_BYTES: Final[int] = 2_000_000
_UTF8_BOM: Final[bytes] = b"\xef\xbb\xbf"

_TSX_SUFFIXES: Final[frozenset[str]] = frozenset({".tsx"})
_TYPESCRIPT_SUFFIXES: Final[frozenset[str]] = frozenset({".ts", ".mts", ".cts"})

# Declaration node types that map directly onto one symbol kind.
_DECLARATION_KINDS: Final[dict[str, SymbolKind]] = {
    "function_declaration": SymbolKind.FUNCTION,
    "generator_function_declaration": SymbolKind.FUNCTION,
    "function_signature": SymbolKind.FUNCTION,
    "class_declaration": SymbolKind.CLASS,
    "abstract_class_declaration": SymbolKind.CLASS,
    "interface_declaration": SymbolKind.INTERFACE,
    "type_alias_declaration": SymbolKind.TYPE_ALIAS,
    "enum_declaration": SymbolKind.ENUM,
    "method_definition": SymbolKind.METHOD,
    "method_signature": SymbolKind.METHOD,
    "public_field_definition": SymbolKind.FIELD,
    "property_signature": SymbolKind.PROPERTY,
}

# Node types that introduce a language-level naming scope for their members.
_CONTAINER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "class_declaration",
        "abstract_class_declaration",
        "interface_declaration",
        "enum_declaration",
    }
)

_FUNCTION_VALUE_TYPES: Final[frozenset[str]] = frozenset(
    {"arrow_function", "function_expression", "function"}
)


class TsJsParser:
    """Extracts TypeScript and JavaScript symbols without executing anything."""

    name = "tsjs"
    version = PARSER_BUNDLE_VERSION
    supported_languages = frozenset({"typescript", "javascript"})

    def __init__(self) -> None:
        self._parsers = {
            "tsx": Parser(Language(language_tsx())),
            "typescript": Parser(Language(language_typescript())),
            "javascript": Parser(Language(javascript_language())),
        }

    def parse(self, request: ParseRequest) -> ParseResult:
        """Parse one TypeScript or JavaScript file into symbols and diagnostics."""
        if not request.content:
            # Same rule as the Python parser: zero lines, nothing to cite.
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=True,
                symbols=(),
                diagnostics=(),
            )
        if len(request.content) > MAX_PARSE_BYTES:
            return self._failed(
                ParseDiagnostic(
                    code="PARSE_TOO_LARGE",
                    message="The file exceeds the maximum parsable size.",
                )
            )

        bom_length = len(_UTF8_BOM) if request.content.startswith(_UTF8_BOM) else 0
        body = request.content[bom_length:]

        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            return self._failed(
                ParseDiagnostic(
                    code="PARSE_DECODE_ERROR",
                    message="The file is not valid UTF-8 text.",
                )
            )

        parser = self._parsers[_grammar_for(request.relative_path)]
        tree = parser.parse(body)
        module_path = _module_path(request.relative_path)
        line_count = max(body.count(b"\n") + (0 if body.endswith(b"\n") else 1), 1)

        module_symbol = _build_symbol(
            request=request,
            kind=SymbolKind.MODULE,
            name=module_path.rsplit(".", 1)[-1],
            qualified_name=module_path,
            module_path=module_path,
            signature=None,
            start_line=1,
            end_line=line_count,
            start_byte=0,
            end_byte=len(request.content),
        )
        declarations = _collect(
            root=tree.root_node,
            request=request,
            module_path=module_path,
            base_offset=bom_length,
        )

        if tree.root_node.has_error:
            # A broken tree must not produce a partial reference set: half the
            # edges of a file look identical to all of them, and there is no way
            # for a reader to tell which they are looking at.
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                symbols=(module_symbol, *declarations),
                diagnostics=(
                    ParseDiagnostic(
                        code="PARSE_SYNTAX_ERROR",
                        message=(
                            "The file contains syntax the grammar could not "
                            "parse; recovered symbols may be incomplete."
                        ),
                    ),
                ),
            )

        extraction = extract_tsjs_references(
            root=tree.root_node,
            module_path=module_path,
            file_id=request.file_id,
            symbol_ids={
                symbol.qualified_name: symbol.symbol_id
                for symbol in (module_symbol, *declarations)
            },
        )

        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            symbols=(module_symbol, *declarations),
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


def _grammar_for(relative_path: str) -> str:
    suffix = _suffix(relative_path)
    if suffix in _TSX_SUFFIXES:
        return "tsx"
    if suffix in _TYPESCRIPT_SUFFIXES:
        return "typescript"
    return "javascript"


def _suffix(relative_path: str) -> str:
    name = relative_path.rsplit("/", 1)[-1]
    return f".{name.rsplit('.', 1)[-1]}" if "." in name else ""


def _collect(
    *,
    root: Node,
    request: ParseRequest,
    module_path: str,
    base_offset: int,
) -> tuple[SymbolRecord, ...]:
    """Walk the tree iteratively, carrying each node's naming prefix.

    Iteration rather than recursion is deliberate: a hostile file can nest
    thousands of levels deep, and a recursive walk would exhaust the stack on
    input the grammar itself handles fine.
    """
    symbols: list[SymbolRecord] = []
    stack: list[tuple[Node, str]] = [(root, "")]

    while stack:
        node, prefix = stack.pop()
        kind = _kind_for(node)
        child_prefix = prefix

        if kind is not None:
            name = _declared_name(node)
            if name:
                qualified_name = f"{prefix}{name}"
                start_byte, end_byte = _span(node, base_offset)
                symbols.append(
                    _build_symbol(
                        request=request,
                        kind=_refine_kind(kind, name),
                        name=name,
                        qualified_name=qualified_name,
                        module_path=module_path,
                        signature=_signature(node),
                        start_line=_start_line(node),
                        end_line=node.end_point[0] + 1,
                        start_byte=start_byte,
                        end_byte=end_byte,
                        visibility=_visibility(node, name),
                    )
                )
                # TypeScript declarations can contain other declarations in
                # type positions: `type A = { id: string }`, function parameter
                # object types, and nested property signatures. Those children
                # need the nearest named declaration in their identity, or two
                # unrelated `{ id: ... }` annotations in one file collide.
                child_prefix = f"{qualified_name}."

        for child in reversed(node.children):
            stack.append((child, child_prefix))

    symbols = _disambiguate_repeated_symbols(request, symbols)
    symbols.sort(key=lambda symbol: (symbol.start_byte, symbol.qualified_name))
    return tuple(symbols)


def _disambiguate_repeated_symbols(
    request: ParseRequest, symbols: list[SymbolRecord]
) -> list[SymbolRecord]:
    """Make repeated anonymous type members addressable without collisions.

    Union types can legitimately contain several anonymous object members with
    the same property name, for example `type Status = { kind: "a" } |
    { kind: "b" }`. Their nearest named declaration is the same, so the normal
    qualified name is the same. Position is the only stable local identity such
    anonymous members have, and the suffix is applied only to repeated names.
    """
    groups: dict[tuple[SymbolKind, str], list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        groups[(symbol.kind, symbol.qualified_name)].append(symbol)

    repeated = {
        key: value for key, value in groups.items() if len(value) > 1
    }
    if not repeated:
        return symbols

    replacements: dict[int, SymbolRecord] = {}
    for items in repeated.values():
        line_counts: dict[int, int] = defaultdict(int)
        for symbol in items:
            line_counts[symbol.start_line] += 1
        for symbol in items:
            suffix = (
                f"#L{symbol.start_line}"
                if line_counts[symbol.start_line] == 1
                else f"#L{symbol.start_line}B{symbol.start_byte}"
            )
            qualified_name = f"{symbol.qualified_name}{suffix}"
            logical_id = symbol_id(
                request.repository_id,
                request.relative_path,
                qualified_name,
                symbol.kind.value,
            )
            replacements[id(symbol)] = replace(
                symbol,
                symbol_id=logical_id,
                symbol_version_id=symbol_version_id(
                    logical_id, symbol.content_hash, PARSER_BUNDLE_VERSION
                ),
                qualified_name=qualified_name,
            )

    return [replacements.get(id(symbol), symbol) for symbol in symbols]


def _kind_for(node: Node) -> SymbolKind | None:
    declared = _DECLARATION_KINDS.get(node.type)
    if declared is not None:
        return declared
    if node.type == "variable_declarator":
        return _variable_kind(node)
    return None


def _variable_kind(node: Node) -> SymbolKind | None:
    """Classify `const x = ...` by what it is bound to.

    An arrow function bound to a name is how most TypeScript functions are
    written, so treating it as a plain constant would lose most of a modern
    codebase's functions.
    """
    if not _is_top_level_binding(node):
        return None
    value = node.child_by_field_name("value")
    if value is not None and value.type in _FUNCTION_VALUE_TYPES:
        return SymbolKind.FUNCTION
    if value is not None:
        return SymbolKind.CONSTANT
    return None


def _is_top_level_binding(node: Node) -> bool:
    """Only module-level bindings become symbols; locals are not declarations."""
    declaration = node.parent
    if declaration is None:
        return False
    container = declaration.parent
    if container is None:
        return False
    if container.type == "export_statement":
        container = container.parent
    return container is not None and container.type == "program"


def _refine_kind(kind: SymbolKind, name: str) -> SymbolKind:
    if kind is SymbolKind.METHOD and name == "constructor":
        return SymbolKind.CONSTRUCTOR
    return kind


def _declared_name(node: Node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return ""
    return name_node.text.decode("utf-8", errors="replace")


def _start_line(node: Node) -> int:
    """Report an exported declaration from its `export` keyword."""
    parent = node.parent
    if parent is not None and parent.type == "export_statement":
        return parent.start_point[0] + 1
    if (
        parent is not None
        and parent.type in {"lexical_declaration", "variable_declaration"}
        and parent.parent is not None
        and parent.parent.type == "export_statement"
    ):
        return parent.parent.start_point[0] + 1
    return node.start_point[0] + 1


def _span(node: Node, base_offset: int) -> tuple[int, int]:
    parent = node.parent
    if parent is not None and parent.type == "export_statement":
        return parent.start_byte + base_offset, parent.end_byte + base_offset
    return node.start_byte + base_offset, node.end_byte + base_offset


def _signature(node: Node) -> str | None:
    parameters = node.child_by_field_name("parameters")
    if parameters is None or parameters.text is None:
        return None
    rendered = parameters.text.decode("utf-8", errors="replace")
    returns = node.child_by_field_name("return_type")
    if returns is not None and returns.text is not None:
        rendered += f" {returns.text.decode('utf-8', errors='replace')}"
    return rendered


def _visibility(node: Node, name: str) -> Visibility:
    if name.startswith(("_", "#")):
        return "private"
    for child in node.children:
        if child.type == "accessibility_modifier" and child.text is not None:
            modifier = child.text.decode("utf-8", errors="replace")
            if modifier in {"private", "protected"}:
                return "private"
    return "public"


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
    start_byte: int,
    end_byte: int,
    visibility: Visibility = "public",
) -> SymbolRecord:
    definition_bytes = request.content[start_byte:end_byte]
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
        start_byte=start_byte,
        end_byte=end_byte,
        content_hash=content_hash,
        visibility=visibility,
    )


def _module_path(relative_path: str) -> str:
    without_suffix = relative_path.rsplit(".", 1)[0]
    dotted = without_suffix.replace("/", ".")
    if dotted.endswith(".index"):
        return dotted[: -len(".index")]
    return dotted
