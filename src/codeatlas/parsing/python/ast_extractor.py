"""Python `ast`-based symbol and relation extraction (Blueprint §4.4.4).

Primary extractor for syntactically valid Python. Produces stable symbols
(classes, functions, methods, constructors, routes, tests) with exact line
spans, qualified names, parent linkage, docstrings, and signatures; plus
CONTAINS / IMPORTS / INHERITS / CALLS / MAY_CALL relations.

Uncertainty is explicit (CLAUDE.md §2.11): only calls resolved to a symbol
defined in the same module (a local function, or ``self.method`` of the
enclosing class) are ``CALLS`` (static_resolved, confidence 1.0). Everything
else — attribute calls on instance state, calls into imported modules — is
``MAY_CALL`` with a heuristic derivation and confidence < 1.0. Calls to
builtins/unknowns are not emitted, to avoid noise.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath

from codeatlas.domain.enums import Derivation, Language, RelationType, SymbolType
from codeatlas.domain.identity import relation_id, symbol_id
from codeatlas.parsing.contracts import ParsedRelation, ParsedSymbol

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "options", "head", "route", "websocket"}
)
_MAY_CALL_CONFIDENCE = 0.5
_IMPORTED_CALL_CONFIDENCE = 0.6

_FunctionDef = ast.FunctionDef | ast.AsyncFunctionDef


def module_qualified_name(relative_path: str) -> str:
    parts = list(PurePosixPath(relative_path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else PurePosixPath(relative_path).stem


@dataclass
class _FunctionRecord:
    node: _FunctionDef
    symbol: ParsedSymbol
    class_qualified_name: str | None


class PythonAstExtractor:
    """Extracts symbols and relations from a valid Python AST."""

    def __init__(self, repository_id: str, relative_path: str) -> None:
        self._repo = repository_id
        self._path = relative_path
        self._symbols: list[ParsedSymbol] = []
        self._relations: list[ParsedRelation] = []
        self._functions: list[_FunctionRecord] = []
        # Resolution tables (built in pass 1).
        self._module_functions: dict[str, str] = {}  # name -> symbol id
        self._class_methods: dict[str, dict[str, str]] = {}  # class qn -> {name: id}
        self._imported_names: set[str] = set()

    def run(self, source: str) -> tuple[list[ParsedSymbol], list[ParsedRelation]]:
        tree = ast.parse(source)
        module = self._make_module_symbol(tree, source)
        self._symbols.append(module)
        self._collect_imports(tree, module)
        self._visit_body(tree.body, parent_id=module.id, qualifier="", class_qn=None)
        self._resolve_calls()
        return self._symbols, self._relations

    # --- Pass 1: symbols -----------------------------------------------------

    def _make_module_symbol(self, tree: ast.Module, source: str) -> ParsedSymbol:
        qn = module_qualified_name(self._path)
        line_count = source.count("\n") + (0 if source.endswith("\n") or not source else 1)
        return ParsedSymbol(
            id=symbol_id(self._repo, self._path, qn, SymbolType.MODULE),
            qualified_name=qn,
            short_name=PurePosixPath(self._path).stem,
            symbol_type=SymbolType.MODULE,
            language=Language.PYTHON,
            start_line=1,
            end_line=max(1, line_count),
            docstring=ast.get_docstring(tree),
        )

    def _visit_body(
        self, body: list[ast.stmt], *, parent_id: str, qualifier: str, class_qn: str | None
    ) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                self._visit_class(node, parent_id=parent_id, qualifier=qualifier)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                self._visit_function(
                    node, parent_id=parent_id, qualifier=qualifier, class_qn=class_qn
                )

    def _visit_class(self, node: ast.ClassDef, *, parent_id: str, qualifier: str) -> None:
        qn = f"{qualifier}.{node.name}" if qualifier else node.name
        symbol_type = SymbolType.INTERFACE if _is_protocol(node) else SymbolType.CLASS
        symbol = ParsedSymbol(
            id=symbol_id(self._repo, self._path, qn, symbol_type),
            qualified_name=qn,
            short_name=node.name,
            symbol_type=symbol_type,
            language=Language.PYTHON,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            parent_id=parent_id,
            signature=f"class {node.name}",
            docstring=ast.get_docstring(node),
            exported=not node.name.startswith("_"),
        )
        self._symbols.append(symbol)
        self._add_relation(
            parent_id,
            RelationType.CONTAINS,
            qn,
            symbol.id,
            node.lineno,
            1.0,
            Derivation.STATIC_RESOLVED,
        )
        for base in node.bases:
            base_name = _name_of(base)
            if base_name is not None:
                self._add_relation(
                    symbol.id,
                    RelationType.INHERITS,
                    base_name,
                    None,
                    node.lineno,
                    1.0,
                    Derivation.AST_ENRICHED,
                )
        self._class_methods.setdefault(qn, {})
        self._visit_body(node.body, parent_id=symbol.id, qualifier=qn, class_qn=qn)

    def _visit_function(
        self, node: _FunctionDef, *, parent_id: str, qualifier: str, class_qn: str | None
    ) -> None:
        qn = f"{qualifier}.{node.name}" if qualifier else node.name
        symbol_type = _classify_function(node, in_class=class_qn is not None)
        symbol = ParsedSymbol(
            id=symbol_id(self._repo, self._path, qn, symbol_type),
            qualified_name=qn,
            short_name=node.name,
            symbol_type=symbol_type,
            language=Language.PYTHON,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            parent_id=parent_id,
            signature=_signature(node),
            docstring=ast.get_docstring(node),
            exported=not node.name.startswith("_"),
        )
        self._symbols.append(symbol)
        self._add_relation(
            parent_id,
            RelationType.CONTAINS,
            qn,
            symbol.id,
            node.lineno,
            1.0,
            Derivation.STATIC_RESOLVED,
        )
        if class_qn is not None:
            self._class_methods.setdefault(class_qn, {})[node.name] = symbol.id
        else:
            self._module_functions[node.name] = symbol.id
        self._functions.append(
            _FunctionRecord(node=node, symbol=symbol, class_qualified_name=class_qn)
        )
        # Recurse to capture nested classes/functions (qualified under this function).
        self._visit_body(node.body, parent_id=symbol.id, qualifier=qn, class_qn=class_qn)

    def _collect_imports(self, tree: ast.Module, module: ParsedSymbol) -> None:
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    self._imported_names.add(bound)
                    self._add_relation(
                        module.id,
                        RelationType.IMPORTS,
                        alias.name,
                        None,
                        node.lineno,
                        1.0,
                        Derivation.STATIC_RESOLVED,
                    )
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    bound = alias.asname or alias.name
                    self._imported_names.add(bound)
                    target = f"{base}.{alias.name}" if base else alias.name
                    self._add_relation(
                        module.id,
                        RelationType.IMPORTS,
                        target,
                        None,
                        node.lineno,
                        1.0,
                        Derivation.STATIC_RESOLVED,
                    )

    # --- Pass 2: calls -------------------------------------------------------

    def _resolve_calls(self) -> None:
        for record in self._functions:
            methods = (
                self._class_methods.get(record.class_qualified_name, {})
                if record.class_qualified_name is not None
                else {}
            )
            for call in _iter_calls(record.node):
                self._resolve_call(record.symbol, call, methods)

    def _resolve_call(
        self, source: ParsedSymbol, call: ast.Call, class_methods: dict[str, str]
    ) -> None:
        func = call.func
        line = call.lineno
        if isinstance(func, ast.Name):
            name = func.id
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
        elif isinstance(func, ast.Attribute):
            attr = func.attr
            value = func.value
            if isinstance(value, ast.Name) and value.id == "self":
                # self.method() — resolvable to a method of the enclosing class.
                if attr in class_methods:
                    self._add_relation(
                        source.id,
                        RelationType.CALLS,
                        attr,
                        class_methods[attr],
                        line,
                        1.0,
                        Derivation.STATIC_RESOLVED,
                    )
                else:
                    self._add_relation(
                        source.id,
                        RelationType.MAY_CALL,
                        attr,
                        None,
                        line,
                        _MAY_CALL_CONFIDENCE,
                        Derivation.NAME_AND_IMPORT_HEURISTIC,
                    )
            elif isinstance(value, ast.Name) and value.id in self._imported_names:
                self._add_relation(
                    source.id,
                    RelationType.MAY_CALL,
                    f"{value.id}.{attr}",
                    None,
                    line,
                    _IMPORTED_CALL_CONFIDENCE,
                    Derivation.NAME_AND_IMPORT_HEURISTIC,
                )
            else:
                # obj.method() / self._attr.method() — target unknown without types.
                self._add_relation(
                    source.id,
                    RelationType.MAY_CALL,
                    attr,
                    None,
                    line,
                    _MAY_CALL_CONFIDENCE,
                    Derivation.NAME_AND_IMPORT_HEURISTIC,
                )

    # --- Helpers -------------------------------------------------------------

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


def _classify_function(node: _FunctionDef, *, in_class: bool) -> SymbolType:
    if _has_route_decorator(node):
        return SymbolType.ROUTE
    if _is_test(node):
        return SymbolType.TEST
    if in_class:
        return SymbolType.CONSTRUCTOR if node.name == "__init__" else SymbolType.METHOD
    return SymbolType.FUNCTION


def _has_route_decorator(node: _FunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr.lower() in _HTTP_METHODS:
            return True
    return False


def _is_test(node: _FunctionDef) -> bool:
    return node.name.startswith("test_") or node.name == "test"


def _is_protocol(node: ast.ClassDef) -> bool:
    return any(_name_of(base) in {"Protocol", "typing.Protocol"} for base in node.bases)


def _name_of(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name_of(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _signature(node: _FunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({args}){returns}"


def _iter_calls(func_node: _FunctionDef) -> list[ast.Call]:
    """Calls in a function's own body, excluding nested function/class scopes."""
    calls: list[ast.Call] = []
    for stmt in func_node.body:
        _walk_calls(stmt, calls)
    return calls


def _walk_calls(node: ast.AST, out: list[ast.Call]) -> None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
        return  # nested scope handled by its own symbol
    if isinstance(node, ast.Call):
        out.append(node)
    for child in ast.iter_child_nodes(node):
        _walk_calls(child, out)
