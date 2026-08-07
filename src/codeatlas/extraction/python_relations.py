"""References stated outright by Python syntax.

This walks the ``ast`` module ``PythonParser`` already built — there is no second
parse — and emits a :class:`SymbolReference` only for constructs whose target is
*written down*. Nothing here infers a type, follows a name to its binding, or
guesses what a variable holds.

The dividing line is worth stating precisely, because it is the difference
between evidence and a guess:

* ``store.claim(key)`` records the name ``claim`` with ``store`` as a receiver
  hint. Resolution may or may not find a match; either way the file really does
  say ``claim``.
* ``handlers[0]()`` records **nothing**. There is no name at the call site to
  record, so any edge would be invented. It is counted as a diagnostic instead,
  so the gap is visible rather than silent.

``self.method()`` is the single case where a receiver's type is known without
inference, because ``self`` is bound by the enclosing class definition.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.extraction.routes import ROUTE_HINT, normalize_route
from codeatlas.parsing.registry import ParseDiagnostic

# Decorator names that take a path as their first argument in the frameworks
# this phase supports. A closed list, because any decorator may be handed a
# path-shaped string and treating each one as a route would invent edges.
_ROUTE_DECORATORS = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "route",
        "websocket",
    }
)

# Calls whose *purpose* is dynamic access. The call itself is real, but the
# access it performs names no target, so recording one would imply knowledge the
# syntax does not contain.
_DYNAMIC_ATTRIBUTE_CALLS = frozenset({"getattr", "setattr", "delattr", "hasattr"})
_DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})

# `-> None` names no type worth citing. Every other annotation name is recorded
# and left for resolution to match or mark external.
_UNCITED_ANNOTATIONS = frozenset({"None"})


@dataclass(frozen=True)
class ReferenceExtraction:
    """References found in one file, plus the gaps that were deliberately left."""

    references: tuple[SymbolReference, ...] = ()
    diagnostics: tuple[ParseDiagnostic, ...] = ()


@dataclass
class _Collector:
    file_id: str
    symbol_ids: Mapping[str, str]
    symbol_kinds: Mapping[str, SymbolKind]
    module_path: str
    references: list[SymbolReference] = field(default_factory=list)
    dynamic_calls: int = 0
    dynamic_attributes: int = 0
    dynamic_imports: int = 0
    star_imports: int = 0
    _seen: dict[tuple[str, str, str, int], int] = field(default_factory=dict)

    def add(
        self,
        *,
        source: str,
        kind: RelationKind,
        target_hint: str,
        module_hint: str,
        start_line: int,
        end_line: int,
    ) -> None:
        """Record one reference, assigning the ordinal that keeps duplicates apart."""
        source_symbol_id = self.symbol_ids.get(source)
        if source_symbol_id is None or not target_hint:
            # A reference with no enclosing symbol has nothing to hang off. This
            # happens only for constructs the parser did not turn into a symbol.
            return

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
                end_line=max(end_line, start_line),
                part=part,
            )
        )

    def add_fixture_parameters(
        self, *, source: str, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Record one reference per parameter pytest would inject into a test.

        Only a TEST symbol is considered. A fixture consumed by another fixture
        is a real pytest behavior, but chaining it would let one weak link
        stand on another, and the resulting edge would be too far from the
        evidence to be worth reporting.
        """
        if self.symbol_kinds.get(source) is not SymbolKind.TEST:
            return
        arguments = node.args
        # A defaulted parameter already has a value, so pytest does not inject
        # it. Defaults bind to the tail of `args`, hence the slice.
        defaulted = len(arguments.defaults)
        positional = arguments.posonlyargs + arguments.args
        injected = (
            positional[: len(positional) - defaulted] if defaulted else positional
        )
        for argument in injected:
            if argument.arg in {"self", "cls"}:
                continue
            self.add(
                source=source,
                kind=RelationKind.CONSUMES_FIXTURE,
                target_hint=argument.arg,
                module_hint="",
                start_line=node.lineno,
                end_line=node.lineno,
            )

    def diagnostics(self) -> tuple[ParseDiagnostic, ...]:
        """Report each unemitted category so the gap is measurable."""
        counted = (
            (
                "REFERENCE_DYNAMIC_CALL",
                self.dynamic_calls,
                "call through a computed callee",
            ),
            (
                "REFERENCE_DYNAMIC_ATTRIBUTE",
                self.dynamic_attributes,
                "dynamic attribute access",
            ),
            ("REFERENCE_DYNAMIC_IMPORT", self.dynamic_imports, "dynamic import"),
            ("REFERENCE_STAR_IMPORT", self.star_imports, "star import"),
        )
        return tuple(
            ParseDiagnostic(
                code=code,
                message=(
                    f"{count} {label}(s) were not recorded as references, because "
                    "the target is not stated in the source."
                ),
            )
            for code, count, label in counted
            if count
        )


def extract_python_references(
    *,
    module: ast.Module,
    module_path: str,
    file_id: str,
    symbol_ids: Mapping[str, str],
    symbol_kinds: Mapping[str, SymbolKind],
) -> ReferenceExtraction:
    """Extract references from an already-parsed Python module.

    ``symbol_ids`` maps a qualified name to the symbol ID the parser assigned, so
    extraction never re-derives symbol kinds or identity. ``symbol_kinds`` maps
    the same qualified names to their kind, so extraction can tell a TEST
    function apart without re-deriving it.
    """
    collector = _Collector(
        file_id=file_id,
        symbol_ids=symbol_ids,
        symbol_kinds=symbol_kinds,
        module_path=module_path,
    )
    _walk_body(
        body=module.body,
        prefix="",
        scope=module_path,
        class_name="",
        collector=collector,
    )
    return ReferenceExtraction(
        references=tuple(collector.references),
        diagnostics=collector.diagnostics(),
    )


def _walk_body(
    *,
    body: list[ast.stmt],
    prefix: str,
    scope: str,
    class_name: str,
    collector: _Collector,
) -> None:
    for node in body:
        if isinstance(node, ast.ClassDef):
            qualified_name = f"{prefix}{node.name}"
            collector.add(
                source=scope,
                kind=RelationKind.CONTAINS,
                target_hint=qualified_name,
                module_hint="",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
            for base in node.bases:
                target, receiver = _name_parts(base)
                if target:
                    collector.add(
                        source=qualified_name,
                        kind=RelationKind.INHERITS,
                        target_hint=target,
                        module_hint=receiver,
                        start_line=base.lineno,
                        end_line=base.end_lineno or base.lineno,
                    )
            for decorator in node.decorator_list:
                _visit_expression(decorator, qualified_name, "", collector)
            _walk_body(
                body=node.body,
                prefix=f"{qualified_name}.",
                scope=qualified_name,
                class_name=qualified_name,
                collector=collector,
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            qualified_name = f"{prefix}{node.name}"
            collector.add(
                source=scope,
                kind=RelationKind.CONTAINS,
                target_hint=qualified_name,
                module_hint="",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
            _collect_annotations(node, qualified_name, collector)
            collector.add_fixture_parameters(source=qualified_name, node=node)
            for decorator in node.decorator_list:
                _collect_route(decorator, qualified_name, collector)
                _visit_expression(decorator, qualified_name, class_name, collector)
            _walk_body(
                body=node.body,
                prefix=f"{qualified_name}.",
                scope=qualified_name,
                # A nested function is still lexically inside the class, so
                # `self` keeps its meaning.
                class_name=class_name,
                collector=collector,
            )
        else:
            _visit_statement(node, scope, class_name, collector)


def _visit_statement(
    node: ast.stmt, scope: str, class_name: str, collector: _Collector
) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            collector.add(
                source=scope,
                kind=RelationKind.IMPORTS,
                target_hint=alias.name,
                module_hint=alias.name,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
        return

    if isinstance(node, ast.ImportFrom):
        module_hint = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                # A star import names no target. Which symbols it binds depends
                # on the other module's contents, which extraction may not read.
                collector.star_imports += 1
                continue
            collector.add(
                source=scope,
                kind=RelationKind.IMPORTS,
                target_hint=alias.name,
                module_hint=module_hint,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
        return

    if isinstance(node, ast.Assign | ast.AnnAssign):
        _collect_exports(node, scope, collector)

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.expr):
            _visit_expression(child, scope, class_name, collector)
        elif isinstance(child, ast.stmt):
            _visit_statement(child, scope, class_name, collector)


def _collect_route(
    decorator: ast.expr, scope: str, collector: _Collector
) -> None:
    """Record the path a route decorator states, if it states one literally.

    ``@app.get(PATH)`` records nothing. The decorator names a variable, and
    reading its value would mean running the module.
    """
    if not isinstance(decorator, ast.Call) or not decorator.args:
        return

    callee = decorator.func
    if isinstance(callee, ast.Attribute):
        name = callee.attr
    elif isinstance(callee, ast.Name):
        name = callee.id
    else:
        return
    if name.lower() not in _ROUTE_DECORATORS:
        return

    first = decorator.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return
    route = normalize_route(first.value)
    if route is None:
        return

    collector.add(
        source=scope,
        kind=RelationKind.ROUTES_TO,
        target_hint=route,
        module_hint=ROUTE_HINT,
        start_line=first.lineno,
        end_line=first.end_lineno or first.lineno,
    )


def _collect_exports(
    node: ast.Assign | ast.AnnAssign, scope: str, collector: _Collector
) -> None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    named = any(
        isinstance(target, ast.Name) and target.id == "__all__" for target in targets
    )
    if not named or node.value is None:
        return

    if not isinstance(node.value, ast.List | ast.Tuple | ast.Set):
        return

    for element in node.value.elts:
        # Only a literal string states an export outright. A name or a call
        # would have to be evaluated to know what it holds.
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            collector.add(
                source=scope,
                kind=RelationKind.EXPORTS,
                target_hint=element.value,
                module_hint="",
                start_line=element.lineno,
                end_line=element.end_lineno or element.lineno,
            )


def _collect_annotations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    scope: str,
    collector: _Collector,
) -> None:
    arguments = node.args
    annotations: list[ast.expr] = [
        argument.annotation
        for group in (arguments.posonlyargs, arguments.args, arguments.kwonlyargs)
        for argument in group
        if argument.annotation is not None
    ]
    for optional in (arguments.vararg, arguments.kwarg):
        if optional is not None and optional.annotation is not None:
            annotations.append(optional.annotation)
    if node.returns is not None:
        annotations.append(node.returns)

    for annotation in annotations:
        for target, receiver, line, end_line in _annotation_names(annotation):
            if target in _UNCITED_ANNOTATIONS:
                continue
            collector.add(
                source=scope,
                kind=RelationKind.REFERENCES,
                target_hint=target,
                module_hint=receiver,
                start_line=line,
                end_line=end_line,
            )


def _annotation_names(
    annotation: ast.expr,
) -> list[tuple[str, str, int, int]]:
    """Flatten an annotation into the names it mentions.

    ``list[Widget]`` mentions both ``list`` and ``Widget``, and a reader asking
    "what types does this touch" wants both.
    """
    found: list[tuple[str, str, int, int]] = []
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name | ast.Attribute):
            target, receiver = _name_parts(node)
            if target:
                found.append(
                    (target, receiver, node.lineno, node.end_lineno or node.lineno)
                )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A string annotation is a forward reference. It names a type
            # outright, so it is recorded as written.
            found.append(
                (node.value, "", node.lineno, node.end_lineno or node.lineno)
            )
    return found


def _visit_expression(
    node: ast.expr, scope: str, class_name: str, collector: _Collector
) -> None:
    if isinstance(node, ast.Call):
        _visit_call(node, scope, class_name, collector)
        return

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.expr):
            _visit_expression(child, scope, class_name, collector)


def _visit_call(
    node: ast.Call, scope: str, class_name: str, collector: _Collector
) -> None:
    callee = node.func

    if isinstance(callee, ast.Name):
        if callee.id in _DYNAMIC_ATTRIBUTE_CALLS:
            collector.dynamic_attributes += 1
        elif callee.id in _DYNAMIC_IMPORT_CALLS:
            collector.dynamic_imports += 1
        else:
            collector.add(
                source=scope,
                kind=RelationKind.CALLS,
                target_hint=callee.id,
                module_hint="",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
    elif isinstance(callee, ast.Attribute):
        receiver = _expression_text(callee.value)
        if callee.attr in _DYNAMIC_IMPORT_CALLS:
            collector.dynamic_imports += 1
        elif callee.attr in _DYNAMIC_ATTRIBUTE_CALLS:
            collector.dynamic_attributes += 1
        elif receiver == "self" and class_name:
            # The one receiver whose type is known without inference.
            collector.add(
                source=scope,
                kind=RelationKind.CALLS,
                target_hint=f"{class_name}.{callee.attr}",
                module_hint="self",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
        else:
            collector.add(
                source=scope,
                kind=RelationKind.CALLS,
                target_hint=callee.attr,
                module_hint=receiver,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
    else:
        # A subscript, lambda, or another call in callee position. There is no
        # name written at this site, so no edge can be recorded honestly.
        collector.dynamic_calls += 1

    # The callee is an expression in its own right and may contain further
    # calls: `foo().bar()` really does call `foo`, and `getattr(o, "n")()` really
    # does call `getattr`. Descending into it is what keeps those visible.
    if isinstance(callee, ast.Attribute):
        _visit_expression(callee.value, scope, class_name, collector)
    elif not isinstance(callee, ast.Name):
        _visit_expression(callee, scope, class_name, collector)

    for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
        _visit_expression(argument, scope, class_name, collector)


def _name_parts(node: ast.expr) -> tuple[str, str]:
    """Split a name or dotted name into ``(final name, receiver text)``."""
    if isinstance(node, ast.Name):
        return node.id, ""
    if isinstance(node, ast.Attribute):
        return node.attr, _expression_text(node.value)
    if isinstance(node, ast.Subscript):
        return _name_parts(node.value)
    return "", ""


def _expression_text(node: ast.expr) -> str:
    """Render a receiver expression, or empty when it is not a plain name path."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expression_text(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""
