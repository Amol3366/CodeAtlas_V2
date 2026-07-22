"""Tree-sitter symbol/relation extraction for JavaScript and TypeScript (Blueprint §4.4).

Shared by the JS and TS parsers. Extracts classes, interfaces, enums, type
aliases, functions, methods, constructors, named arrow/function consts, plus
route (Express-style) and test (jest/vitest/mocha) symbols. Emits
CONTAINS / IMPORTS / INHERITS / CALLS / MAY_CALL.

Uncertainty is explicit (CLAUDE.md §2.11): only calls to a same-module top-level
function (or ``this.method`` of the enclosing class) are ``CALLS`` (static, 1.0).
Everything else is ``MAY_CALL`` (< 1.0, heuristic). Module resolution is
path-arithmetic only: relative specifiers resolve to a repo-relative module path
(``static_resolved``); non-relative specifiers — bare packages *and* path
aliases — are never ``static_resolved`` (they get a heuristic derivation), so an
unresolved alias can never masquerade as a certain edge.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath

from tree_sitter import Node, Parser

from codeatlas.domain.enums import Derivation, Language, RelationType, SymbolType
from codeatlas.domain.identity import relation_id, symbol_id
from codeatlas.parsing.contracts import ParsedRelation, ParsedSymbol

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "options", "head", "all", "use", "route"}
)
_TEST_FUNCTIONS = frozenset({"it", "test"})
_NESTED_SCOPES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "class_declaration",
        "class_body",
    }
)
_MAY_CALL_CONFIDENCE = 0.5
_IMPORTED_CALL_CONFIDENCE = 0.6
_ALIAS_IMPORT_CONFIDENCE = 0.7


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _module_qualified_name(relative_path: str) -> str:
    return PurePosixPath(relative_path).stem


@dataclass
class _FunctionRecord:
    symbol: ParsedSymbol
    body: Node | None
    class_qualified_name: str | None


class JsTsExtractor:
    def __init__(self, repository_id: str, relative_path: str, language: Language) -> None:
        self._repo = repository_id
        self._path = relative_path
        self._language = language
        self._symbols: list[ParsedSymbol] = []
        self._relations: list[ParsedRelation] = []
        self._functions: list[_FunctionRecord] = []
        self._module_functions: dict[str, str] = {}
        self._class_methods: dict[str, dict[str, str]] = {}
        self._imported_names: set[str] = set()
        self._created_qns: set[str] = set()
        self._module_id = ""

    def run(
        self, parser: Parser, source: bytes
    ) -> tuple[list[ParsedSymbol], list[ParsedRelation], bool]:
        root = parser.parse(source).root_node
        module = self._make_module(root)
        self._module_id = module.id
        self._symbols.append(module)
        for child in root.children:
            self._scan_top(child, module.id, exported=False)
        self._scan_routes_and_tests(root, module.id)
        self._resolve_calls()
        return self._symbols, self._relations, root.has_error

    # --- Symbols -------------------------------------------------------------

    def _make_module(self, root: Node) -> ParsedSymbol:
        qn = _module_qualified_name(self._path)
        return ParsedSymbol(
            id=symbol_id(self._repo, self._path, qn, SymbolType.MODULE),
            qualified_name=qn,
            short_name=qn,
            symbol_type=SymbolType.MODULE,
            language=self._language,
            start_line=1,
            end_line=max(1, root.end_point.row + 1),
        )

    def _scan_top(self, node: Node, parent_id: str, *, exported: bool) -> None:
        kind = node.type
        if kind == "export_statement":
            for child in node.named_children:
                self._scan_top(child, parent_id, exported=True)
            return
        if kind == "import_statement":
            self._handle_import(node)
        elif kind in {"class_declaration", "abstract_class_declaration"}:
            self._handle_class(node, parent_id, exported=exported)
        elif kind == "interface_declaration":
            self._simple_symbol(node, SymbolType.INTERFACE, parent_id, exported=exported)
        elif kind == "enum_declaration":
            self._simple_symbol(node, SymbolType.ENUM, parent_id, exported=exported)
        elif kind == "type_alias_declaration":
            self._simple_symbol(node, SymbolType.TYPE_ALIAS, parent_id, exported=exported)
        elif kind in {"function_declaration", "generator_function_declaration"}:
            self._handle_function(node, parent_id, class_qn=None, exported=exported)
        elif kind in {"lexical_declaration", "variable_declaration"}:
            self._handle_variables(node, parent_id, exported=exported)

    def _simple_symbol(
        self, node: Node, symbol_type: SymbolType, parent_id: str, *, exported: bool
    ) -> ParsedSymbol | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        name = _text(name_node)
        symbol = self._add_symbol(
            name, name, symbol_type, node, parent_id=parent_id, exported=exported
        )
        return symbol

    def _handle_class(self, node: Node, parent_id: str, *, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        symbol = self._add_symbol(
            name,
            name,
            SymbolType.CLASS,
            node,
            parent_id=parent_id,
            exported=exported,
            signature=f"class {name}",
        )
        self._class_methods.setdefault(name, {})
        for base in _extends_targets(node):
            self._add_relation(
                symbol.id,
                RelationType.INHERITS,
                base,
                None,
                node.start_point.row + 1,
                1.0,
                Derivation.AST_ENRICHED,
            )
        body = node.child_by_field_name("body")
        if body is not None:
            for member in body.named_children:
                if member.type == "method_definition":
                    self._handle_method(member, symbol.id, class_qn=name)

    def _handle_method(self, node: Node, parent_id: str, *, class_qn: str) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        qn = f"{class_qn}.{name}"
        symbol_type = SymbolType.CONSTRUCTOR if name == "constructor" else SymbolType.METHOD
        symbol = self._add_symbol(
            qn,
            name,
            symbol_type,
            node,
            parent_id=parent_id,
            exported=not name.startswith("_"),
            signature=_signature(node, name),
        )
        self._class_methods.setdefault(class_qn, {})[name] = symbol.id
        self._functions.append(_FunctionRecord(symbol, node.child_by_field_name("body"), class_qn))

    def _handle_function(
        self, node: Node, parent_id: str, *, class_qn: str | None, exported: bool
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        symbol = self._add_symbol(
            name,
            name,
            SymbolType.FUNCTION,
            node,
            parent_id=parent_id,
            exported=exported,
            signature=_signature(node, name),
        )
        self._module_functions[name] = symbol.id
        self._functions.append(_FunctionRecord(symbol, node.child_by_field_name("body"), class_qn))

    def _handle_variables(self, node: Node, parent_id: str, *, exported: bool) -> None:
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue
            name = _text(name_node)
            value = declarator.child_by_field_name("value")
            if value is not None and value.type in {"arrow_function", "function_expression"}:
                symbol = self._add_symbol(
                    name,
                    name,
                    SymbolType.FUNCTION,
                    declarator,
                    parent_id=parent_id,
                    exported=exported,
                    signature=_signature(value, name),
                )
                self._module_functions[name] = symbol.id
                self._functions.append(
                    _FunctionRecord(symbol, value.child_by_field_name("body"), None)
                )
            else:
                self._add_symbol(
                    name,
                    name,
                    SymbolType.CONSTANT,
                    declarator,
                    parent_id=parent_id,
                    exported=exported,
                )

    def _add_symbol(
        self,
        qualified_name: str,
        short_name: str,
        symbol_type: SymbolType,
        node: Node,
        *,
        parent_id: str,
        exported: bool,
        signature: str | None = None,
    ) -> ParsedSymbol:
        symbol = ParsedSymbol(
            id=symbol_id(self._repo, self._path, qualified_name, symbol_type),
            qualified_name=qualified_name,
            short_name=short_name,
            symbol_type=symbol_type,
            language=self._language,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parent_id=parent_id,
            signature=signature,
            docstring=_leading_comment(node),
            exported=exported,
        )
        self._symbols.append(symbol)
        self._created_qns.add(qualified_name)
        self._add_relation(
            parent_id,
            RelationType.CONTAINS,
            qualified_name,
            symbol.id,
            node.start_point.row + 1,
            1.0,
            Derivation.STATIC_RESOLVED,
        )
        return symbol

    # --- Imports -------------------------------------------------------------

    def _handle_import(self, node: Node) -> None:
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return
        specifier = _text(source_node).strip("\"'`")
        resolved, is_static = self._resolve_module(specifier)
        for bound, original in _imported_names(node):
            self._imported_names.add(bound)
            target = f"{resolved}.{original}"
            if is_static:
                self._add_relation(
                    self._module_id,
                    RelationType.IMPORTS,
                    target,
                    None,
                    node.start_point.row + 1,
                    1.0,
                    Derivation.STATIC_RESOLVED,
                )
            else:
                self._add_relation(
                    self._module_id,
                    RelationType.IMPORTS,
                    target,
                    None,
                    node.start_point.row + 1,
                    _ALIAS_IMPORT_CONFIDENCE,
                    Derivation.NAME_AND_IMPORT_HEURISTIC,
                )

    def _resolve_module(self, specifier: str) -> tuple[str, bool]:
        if specifier.startswith("."):
            base = PurePosixPath(self._path).parent.as_posix()
            resolved = posixpath.normpath(posixpath.join(base, specifier))
            return resolved, True
        # Bare packages and path aliases are never resolved to a certain repo edge.
        return specifier, False

    # --- Routes & tests ------------------------------------------------------

    def _scan_routes_and_tests(self, root: Node, module_id: str) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                self._maybe_route_or_test(node, module_id)
            stack.extend(node.children)

    def _maybe_route_or_test(self, call: Node, module_id: str) -> None:
        func = call.child_by_field_name("function")
        args = call.child_by_field_name("arguments")
        if func is None:
            return
        if func.type == "member_expression":
            obj = func.child_by_field_name("object")
            prop = func.child_by_field_name("property")
            if obj is not None and obj.type == "identifier" and prop is not None:
                method = _text(prop).lower()
                if method in _HTTP_METHODS and method != "use":
                    path = _first_string_arg(args)
                    if path:
                        qn = f"{method.upper()} {path}"
                        self._route_or_test_symbol(qn, path, SymbolType.ROUTE, call, module_id)
        elif func.type == "identifier" and _text(func) in _TEST_FUNCTIONS:
            label = _first_string_arg(args)
            if label:
                self._route_or_test_symbol(label, label, SymbolType.TEST, call, module_id)

    def _route_or_test_symbol(
        self,
        qualified_name: str,
        short_name: str,
        symbol_type: SymbolType,
        node: Node,
        module_id: str,
    ) -> None:
        if qualified_name in self._created_qns:
            return
        self._add_symbol(
            qualified_name,
            short_name,
            symbol_type,
            node,
            parent_id=module_id,
            exported=False,
        )

    # --- Calls ---------------------------------------------------------------

    def _resolve_calls(self) -> None:
        for record in self._functions:
            methods = (
                self._class_methods.get(record.class_qualified_name, {})
                if record.class_qualified_name is not None
                else {}
            )
            for call in self._iter_calls(record.body):
                self._resolve_call(record.symbol, call, methods)

    def _resolve_call(
        self, source: ParsedSymbol, call: Node, class_methods: dict[str, str]
    ) -> None:
        func = call.child_by_field_name("function")
        if func is None:
            return
        line = call.start_point.row + 1
        if func.type == "identifier":
            name = _text(func)
            if name in self._module_functions:
                self._add_relation(
                    source.id,
                    RelationType.CALLS,
                    name,
                    self._module_functions[name],
                    line,
                    1.0,
                    Derivation.STATIC_RESOLVED,
                )
            elif name in self._imported_names:
                self._add_relation(
                    source.id,
                    RelationType.MAY_CALL,
                    name,
                    None,
                    line,
                    _IMPORTED_CALL_CONFIDENCE,
                    Derivation.NAME_AND_IMPORT_HEURISTIC,
                )
        elif func.type == "member_expression":
            obj = func.child_by_field_name("object")
            prop = func.child_by_field_name("property")
            if prop is None:
                return
            method = _text(prop)
            obj_name = _text(obj) if obj is not None else ""
            if obj is not None and obj.type == "this" and method in class_methods:
                self._add_relation(
                    source.id,
                    RelationType.CALLS,
                    method,
                    class_methods[method],
                    line,
                    1.0,
                    Derivation.STATIC_RESOLVED,
                )
            elif obj is not None and obj.type == "identifier" and obj_name in self._imported_names:
                self._add_relation(
                    source.id,
                    RelationType.MAY_CALL,
                    f"{obj_name}.{method}",
                    None,
                    line,
                    _IMPORTED_CALL_CONFIDENCE,
                    Derivation.NAME_AND_IMPORT_HEURISTIC,
                )
            else:
                self._add_relation(
                    source.id,
                    RelationType.MAY_CALL,
                    method,
                    None,
                    line,
                    _MAY_CALL_CONFIDENCE,
                    Derivation.NAME_AND_IMPORT_HEURISTIC,
                )

    def _iter_calls(self, body: Node | None) -> list[Node]:
        calls: list[Node] = []
        if body is None:
            return calls

        def recurse(node: Node) -> None:
            for child in node.children:
                if child.type in _NESTED_SCOPES:
                    continue
                if child.type == "call_expression":
                    calls.append(child)
                recurse(child)

        recurse(body)
        return calls

    # --- Relations -----------------------------------------------------------

    def _add_relation(
        self,
        source_id: str,
        relation_type: RelationType,
        target_name: str,
        target_id: str | None,
        line: int,
        confidence: float,
        derivation: Derivation,
    ) -> None:
        self._relations.append(
            ParsedRelation(
                id=relation_id(source_id, relation_type, target_name, line),
                source_id=source_id,
                relation_type=relation_type,
                target_name=target_name,
                target_id=target_id,
                confidence=confidence,
                derivation=derivation,
                evidence_start_line=line,
                evidence_end_line=line,
            )
        )


def _signature(node: Node, name: str) -> str:
    params = _text(node.child_by_field_name("parameters")) or "()"
    return_type = node.child_by_field_name("return_type")
    suffix = f" {_text(return_type)}" if return_type is not None else ""
    return f"{name}{params}{suffix}"


def _extends_targets(class_node: Node) -> list[str]:
    for child in class_node.children:
        if child.type == "class_heritage":
            names: list[str] = []
            for sub in child.children:
                if sub.type in {"identifier", "type_identifier"}:
                    names.append(_text(sub))
                elif sub.type == "extends_clause":
                    names.extend(
                        _text(t)
                        for t in sub.children
                        if t.type in {"identifier", "type_identifier"}
                    )
            return names
    return []


def _first_string_arg(args: Node | None) -> str | None:
    if args is None:
        return None
    for child in args.named_children:
        if child.type in {"string", "template_string"}:
            return _text(child).strip("\"'`")
    return None


def _leading_comment(node: Node) -> str | None:
    anchor = node
    if node.parent is not None and node.parent.type == "export_statement":
        anchor = node.parent
    prev = anchor.prev_sibling
    if prev is not None and prev.type == "comment":
        text = _text(prev).lstrip("/*").rstrip("*/").strip()
        return text or None
    return None


def _imported_names(import_node: Node) -> list[tuple[str, str]]:
    """Return (bound_name, original_name) pairs for an import statement."""
    pairs: list[tuple[str, str]] = []
    clause = next((c for c in import_node.named_children if c.type == "import_clause"), None)
    if clause is None:
        return pairs
    for child in clause.named_children:
        if child.type == "identifier":  # default import
            pairs.append((_text(child), "default"))
        elif child.type == "namespace_import":
            ident = next((c for c in child.named_children if c.type == "identifier"), None)
            if ident is not None:
                pairs.append((_text(ident), "*"))
        elif child.type == "named_imports":
            for spec in child.named_children:
                if spec.type == "import_specifier":
                    original = _text(spec.child_by_field_name("name"))
                    alias_node = spec.child_by_field_name("alias")
                    bound = _text(alias_node) if alias_node is not None else original
                    pairs.append((bound, original))
    return pairs
