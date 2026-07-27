"""References stated outright by TypeScript and JavaScript syntax.

This walks the Tree-sitter tree ``TsJsParser`` already built — there is no second
parse — and applies the same rule the Python extractor does: record only what is
*written down*.

A module specifier is recorded exactly as written, including its case. Resolving
it happens later and is deliberately case-sensitive, because a case-insensitive
Windows filesystem would otherwise let the same repository resolve differently
than it does on Linux. Normalizing here would destroy the evidence needed to
detect that.

``this.m()`` is the one receiver whose type is known without inference, because
``this`` is bound by the enclosing class. Every other member call carries its
receiver as a hint and lets resolution decide.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from tree_sitter import Node

from codeatlas.contracts import RelationKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.extraction.routes import ROUTE_HINT, normalize_route
from codeatlas.parsing.registry import ParseDiagnostic

# Receivers whose calls address an HTTP path rather than a repository symbol.
# Deliberately a closed list: any member call could be given a path-shaped
# string, and treating every one as a route would fabricate edges.
_HTTP_CLIENTS: Final[frozenset[str]] = frozenset({"axios", "fetch"})

_STRING_TYPES: Final[frozenset[str]] = frozenset({"string", "template_string"})

_CONTAINER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "class_declaration",
        "abstract_class_declaration",
        "interface_declaration",
        "enum_declaration",
    }
)

_FUNCTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
        "method_signature",
        "function_signature",
    }
)

_NAMED_CALLEE_TYPES: Final[frozenset[str]] = frozenset(
    {"identifier", "member_expression"}
)


@dataclass(frozen=True)
class ReferenceExtraction:
    """References found in one file, plus the gaps deliberately left."""

    references: tuple[SymbolReference, ...] = ()
    diagnostics: tuple[ParseDiagnostic, ...] = ()


@dataclass
class _Collector:
    file_id: str
    symbol_ids: Mapping[str, str]
    references: list[SymbolReference] = field(default_factory=list)
    dynamic_calls: int = 0
    _seen: dict[tuple[str, str, str, int], int] = field(default_factory=dict)

    def add(
        self,
        *,
        source: str,
        kind: RelationKind,
        target_hint: str,
        module_hint: str,
        node: Node,
    ) -> None:
        source_symbol_id = self.symbol_ids.get(source)
        if source_symbol_id is None or not target_hint:
            return

        start_line = node.start_point[0] + 1
        key = (source_symbol_id, kind.value, target_hint, start_line)
        part = self._seen.get(key, 0)
        self._seen[key] = part + 1
        self.references.append(
            SymbolReference(
                source_symbol_id=source_symbol_id,
                file_id=self.file_id,
                kind=kind,
                target_hint=target_hint,
                module_hint=module_hint,
                start_line=start_line,
                end_line=max(node.end_point[0] + 1, start_line),
                part=part,
            )
        )

    def diagnostics(self) -> tuple[ParseDiagnostic, ...]:
        if not self.dynamic_calls:
            return ()
        return (
            ParseDiagnostic(
                code="REFERENCE_DYNAMIC_CALL",
                message=(
                    f"{self.dynamic_calls} call(s) through a computed callee were "
                    "not recorded, because the target is not stated in the source."
                ),
            ),
        )


def extract_tsjs_references(
    *,
    root: Node,
    module_path: str,
    file_id: str,
    symbol_ids: Mapping[str, str],
) -> ReferenceExtraction:
    """Extract references from an already-parsed TypeScript/JavaScript tree."""
    collector = _Collector(file_id=file_id, symbol_ids=symbol_ids)
    _walk(
        node=root,
        prefix="",
        scope=module_path,
        class_name="",
        collector=collector,
    )
    return ReferenceExtraction(
        references=tuple(collector.references),
        diagnostics=collector.diagnostics(),
    )


def _walk(
    *,
    node: Node,
    prefix: str,
    scope: str,
    class_name: str,
    collector: _Collector,
) -> None:
    """Walk the tree iteratively, carrying naming and class context.

    Iterative for the same reason the parser's walk is: a hostile file can nest
    far deeper than the interpreter's stack allows.
    """
    stack: list[tuple[Node, str, str, str]] = [(node, prefix, scope, class_name)]

    while stack:
        current, current_prefix, current_scope, current_class = stack.pop()
        child_prefix, child_scope, child_class = (
            current_prefix,
            current_scope,
            current_class,
        )

        declared = _declared_name(current)
        if declared and (
            current.type in _CONTAINER_TYPES or current.type in _FUNCTION_TYPES
        ):
            qualified_name = f"{current_prefix}{declared}"
            collector.add(
                source=current_scope,
                kind=RelationKind.CONTAINS,
                target_hint=qualified_name,
                module_hint="",
                node=current,
            )
            child_scope = qualified_name
            if current.type in _CONTAINER_TYPES:
                child_prefix = f"{qualified_name}."
                child_class = qualified_name
        elif current.type == "variable_declarator" and declared:
            qualified_name = f"{current_prefix}{declared}"
            if qualified_name in collector.symbol_ids:
                child_scope = qualified_name
                _visit_initializer(current, qualified_name, collector)

        _visit(current, current_scope, current_class, collector)

        for child in reversed(current.children):
            stack.append((child, child_prefix, child_scope, child_class))


def _visit(
    node: Node, scope: str, class_name: str, collector: _Collector
) -> None:
    if node.type == "import_statement":
        _visit_import(node, scope, collector)
    elif node.type == "export_statement":
        _visit_export(node, scope, collector)
    elif node.type == "extends_clause":
        _visit_heritage(node, scope, RelationKind.INHERITS, collector)
    elif node.type == "implements_clause":
        _visit_heritage(node, scope, RelationKind.IMPLEMENTS, collector)
    elif node.type == "call_expression":
        _visit_call(node, scope, class_name, collector)
    elif node.type == "new_expression":
        _visit_new(node, scope, collector)
    elif node.type == "type_annotation":
        _visit_type_annotation(node, scope, collector)


def _visit_import(node: Node, scope: str, collector: _Collector) -> None:
    specifier = _string_value(node.child_by_field_name("source"))
    if not specifier:
        return

    clause = _first_child_of_type(node, "import_clause")
    if clause is None:
        # `import "./side-effect";` names no binding but is still a real
        # dependency, so the module is recorded with no target name.
        collector.add(
            source=scope,
            kind=RelationKind.IMPORTS,
            target_hint=specifier,
            module_hint=specifier,
            node=node,
        )
        return

    for child in clause.children:
        if child.type == "identifier":
            collector.add(
                source=scope,
                kind=RelationKind.IMPORTS,
                target_hint="default",
                module_hint=specifier,
                node=node,
            )
        elif child.type == "namespace_import":
            collector.add(
                source=scope,
                kind=RelationKind.IMPORTS,
                target_hint=specifier,
                module_hint=specifier,
                node=node,
            )
        elif child.type == "named_imports":
            for entry in child.children:
                if entry.type != "import_specifier":
                    continue
                name = _text(entry.child_by_field_name("name"))
                if name:
                    collector.add(
                        source=scope,
                        kind=RelationKind.IMPORTS,
                        target_hint=name,
                        module_hint=specifier,
                        node=node,
                    )


def _visit_export(node: Node, scope: str, collector: _Collector) -> None:
    declaration = node.child_by_field_name("declaration")
    if declaration is not None:
        for name in _declared_names(declaration):
            collector.add(
                source=scope,
                kind=RelationKind.EXPORTS,
                target_hint=name,
                module_hint="",
                node=node,
            )
        return

    clause = _first_child_of_type(node, "export_clause")
    if clause is not None:
        for entry in clause.children:
            if entry.type != "export_specifier":
                continue
            name = _text(entry.child_by_field_name("name"))
            if name:
                collector.add(
                    source=scope,
                    kind=RelationKind.EXPORTS,
                    target_hint=name,
                    module_hint="",
                    node=node,
                )
        return

    if any(child.type == "default" for child in node.children):
        collector.add(
            source=scope,
            kind=RelationKind.EXPORTS,
            target_hint="default",
            module_hint="",
            node=node,
        )


def _visit_heritage(
    node: Node, scope: str, kind: RelationKind, collector: _Collector
) -> None:
    for child in node.children:
        if child.type in {"identifier", "type_identifier"}:
            name = _text(child)
            if name:
                collector.add(
                    source=scope,
                    kind=kind,
                    target_hint=name,
                    module_hint="",
                    node=child,
                )
        elif child.type == "member_expression":
            target, receiver = _member_parts(child)
            if target:
                collector.add(
                    source=scope,
                    kind=kind,
                    target_hint=target,
                    module_hint=receiver,
                    node=child,
                )


def _visit_initializer(
    node: Node, scope: str, collector: _Collector
) -> None:
    """Record a route literal a constant holds.

    ``const healthPath = "/health"`` states a path without calling anything. The
    constant is not a caller, so what this records is only that the two name the
    same path; resolution decides what kind of edge that justifies.
    """
    route = _literal_route(node.child_by_field_name("value"))
    if route is not None:
        collector.add(
            source=scope,
            kind=RelationKind.ROUTES_TO,
            target_hint=route,
            module_hint=ROUTE_HINT,
            node=node,
        )


def _visit_call(
    node: Node, scope: str, class_name: str, collector: _Collector
) -> None:
    callee = node.child_by_field_name("function")
    if callee is None:
        return

    _visit_route_call(node, callee, scope, collector)

    if callee.type == "identifier":
        name = _text(callee)
        if name:
            collector.add(
                source=scope,
                kind=RelationKind.CALLS,
                target_hint=name,
                module_hint="",
                node=node,
            )
        return

    if callee.type == "member_expression":
        target, receiver = _member_parts(callee)
        if not target:
            return
        if receiver == "this" and class_name:
            collector.add(
                source=scope,
                kind=RelationKind.CALLS,
                target_hint=f"{class_name}.{target}",
                module_hint="this",
                node=node,
            )
        else:
            collector.add(
                source=scope,
                kind=RelationKind.CALLS,
                target_hint=target,
                module_hint=receiver,
                node=node,
            )
        return

    if callee.type not in _NAMED_CALLEE_TYPES:
        # A subscript, a parenthesized expression, or another call. No name is
        # written at this site, so no edge can be recorded honestly.
        collector.dynamic_calls += 1


def _visit_route_call(
    node: Node, callee: Node, scope: str, collector: _Collector
) -> None:
    """Record the path an HTTP client call addresses, when it is written down.

    ``fetch(url)`` records nothing: the path is in a variable, and following it
    would mean evaluating the program.
    """
    if not _is_http_client(callee):
        return
    route = _literal_route(_first_argument(node))
    if route is not None:
        collector.add(
            source=scope,
            kind=RelationKind.ROUTES_TO,
            target_hint=route,
            module_hint=ROUTE_HINT,
            node=node,
        )


def _is_http_client(callee: Node) -> bool:
    if callee.type == "identifier":
        return _text(callee) in _HTTP_CLIENTS
    if callee.type == "member_expression":
        _, receiver = _member_parts(callee)
        return receiver in _HTTP_CLIENTS
    return False


def _first_argument(node: Node) -> Node | None:
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return None
    for child in arguments.children:
        if child.is_named:
            return child
    return None


def _literal_route(node: Node | None) -> str | None:
    """Read a string or template literal as a normalized route, or ``None``."""
    if node is None or node.type not in _STRING_TYPES:
        return None
    raw = _text(node)
    if len(raw) >= 2 and raw[0] in "\"'`" and raw[-1] == raw[0]:
        raw = raw[1:-1]
    return normalize_route(raw)


def _visit_new(node: Node, scope: str, collector: _Collector) -> None:
    constructor = node.child_by_field_name("constructor")
    if constructor is None:
        return
    if constructor.type in {"identifier", "type_identifier"}:
        name = _text(constructor)
        if name:
            collector.add(
                source=scope,
                kind=RelationKind.REFERENCES,
                target_hint=name,
                module_hint="",
                node=constructor,
            )
    elif constructor.type == "member_expression":
        target, receiver = _member_parts(constructor)
        if target:
            collector.add(
                source=scope,
                kind=RelationKind.REFERENCES,
                target_hint=target,
                module_hint=receiver,
                node=constructor,
            )


def _visit_type_annotation(node: Node, scope: str, collector: _Collector) -> None:
    for descendant in _descendants(node):
        if descendant.type == "type_identifier":
            name = _text(descendant)
            if name:
                collector.add(
                    source=scope,
                    kind=RelationKind.REFERENCES,
                    target_hint=name,
                    module_hint="",
                    node=descendant,
                )


def _descendants(node: Node) -> list[Node]:
    found: list[Node] = []
    stack = list(node.children)
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(current.children)
    return found


def _declared_name(node: Node) -> str:
    return _text(node.child_by_field_name("name"))


def _declared_names(declaration: Node) -> list[str]:
    """Names a declaration introduces, including each `const a = 1, b = 2`."""
    direct = _declared_name(declaration)
    if direct:
        return [direct]
    names: list[str] = []
    for child in declaration.children:
        if child.type == "variable_declarator":
            name = _declared_name(child)
            if name:
                names.append(name)
    return names


def _member_parts(node: Node) -> tuple[str, str]:
    """Split a member expression into ``(property, receiver text)``."""
    target = _text(node.child_by_field_name("property"))
    receiver_node = node.child_by_field_name("object")
    if receiver_node is None:
        return target, ""
    if receiver_node.type == "this":
        return target, "this"
    if receiver_node.type == "identifier":
        return target, _text(receiver_node)
    if receiver_node.type == "member_expression":
        inner_target, inner_receiver = _member_parts(receiver_node)
        joined = f"{inner_receiver}.{inner_target}" if inner_receiver else inner_target
        return target, joined
    return target, ""


def _first_child_of_type(node: Node, node_type: str) -> Node | None:
    for child in node.children:
        if child.type == node_type:
            return child
    return None


def _string_value(node: Node | None) -> str:
    """Read a string literal's contents without its quotes."""
    if node is None:
        return ""
    for child in node.children:
        if child.type == "string_fragment":
            return _text(child)
    return ""


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")
