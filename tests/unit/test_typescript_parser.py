"""Tests for the TypeScript parser (Blueprint §4.4, Phase 4)."""

from __future__ import annotations

from pathlib import Path

from codeatlas.domain.enums import Language, RelationType, SymbolType
from codeatlas.parsing.contracts import ParseRequest, ParseResult
from codeatlas.parsing.registry import default_registry
from codeatlas.parsing.typescript.parser import TypeScriptParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TS_ROOT = FIXTURES / "typescript_repo"


def _parse(root: Path, rel: str) -> ParseResult:
    content = (root / rel).read_bytes()
    return TypeScriptParser().parse(ParseRequest("repo_x", rel, Language.TYPESCRIPT, content))


def _by_qn(result: ParseResult) -> dict[str, SymbolType]:
    return {s.qualified_name: s.symbol_type for s in result.symbols}


def test_classes_methods_and_constructor() -> None:
    symbols = _by_qn(_parse(TS_ROOT, "src/services/orderService.ts"))
    assert symbols["OrderService"] is SymbolType.CLASS
    assert symbols["OrderService.createOrder"] is SymbolType.METHOD
    assert symbols["OrderService.constructor"] is SymbolType.CONSTRUCTOR


def test_interface_enum_type_alias() -> None:
    symbols = _by_qn(_parse(TS_ROOT, "src/types/order.ts"))
    assert symbols["OrderStatus"] is SymbolType.ENUM
    assert symbols["Order"] is SymbolType.INTERFACE
    assert symbols["OrderId"] is SymbolType.TYPE_ALIAS


def test_function_and_exported_const() -> None:
    settings = _by_qn(_parse(TS_ROOT, "src/config/settings.ts"))
    assert settings["getSettings"] is SymbolType.FUNCTION
    routes = _parse(TS_ROOT, "src/routes/orderRoutes.ts")
    by_qn = _by_qn(routes)
    assert by_qn["orderRouter"] is SymbolType.CONSTANT
    # Express route heuristic.
    assert by_qn["POST /orders"] is SymbolType.ROUTE


def test_async_method_in_other_fixture() -> None:
    symbols = _by_qn(_parse(FIXTURES / "mixed_repo", "frontend/client.ts"))
    assert symbols["NotificationClient.notify"] is SymbolType.METHOD


def test_test_symbols_detected_inside_describe() -> None:
    symbols = _by_qn(_parse(TS_ROOT, "test/orderService.test.ts"))
    tests = [qn for qn, t in symbols.items() if t is SymbolType.TEST]
    assert "reserves inventory when available" in tests
    assert len(tests) == 3


def test_relative_imports_are_static_external_are_heuristic() -> None:
    result = _parse(TS_ROOT, "src/routes/orderRoutes.ts")
    imports = [r for r in result.relations if r.relation_type is RelationType.IMPORTS]
    relative = [r for r in imports if r.target_name.startswith("src/")]
    external = [r for r in imports if r.target_name.startswith("express.")]
    assert relative and all(r.derivation.value == "static_resolved" for r in relative)
    assert external and all(r.derivation.value != "static_resolved" for r in external)


def test_path_alias_never_static_resolved() -> None:
    source = b'import { Thing } from "@app/thing";\nimport { Local } from "./local";\n'
    result = TypeScriptParser().parse(ParseRequest("r", "src/a.ts", Language.TYPESCRIPT, source))
    imports = {
        r.target_name: r for r in result.relations if r.relation_type is RelationType.IMPORTS
    }
    alias = imports["@app/thing.Thing"]
    local = imports["src/local.Local"]
    assert alias.derivation.value != "static_resolved"
    assert alias.confidence < 1.0
    assert local.derivation.value == "static_resolved"


def test_may_calls_are_heuristic_and_calls_are_static() -> None:
    # Fixture: this.inventory.reserve(...) is an uncertain member call.
    result = _parse(TS_ROOT, "src/services/orderService.ts")
    may_calls = [r for r in result.relations if r.relation_type is RelationType.MAY_CALL]
    assert may_calls
    for rel in may_calls:
        assert rel.confidence < 1.0
        assert rel.derivation.value != "static_resolved"

    # Inline: a same-module function call resolves to CALLS (static, 1.0).
    inline = b"function a(){ return b(); }\nfunction b(){ return 1; }\n"
    parsed = TypeScriptParser().parse(ParseRequest("r", "x.ts", Language.TYPESCRIPT, inline))
    calls = [r for r in parsed.relations if r.relation_type is RelationType.CALLS]
    assert calls and all(r.confidence == 1.0 and r.target_id is not None for r in calls)


def test_parse_is_idempotent() -> None:
    first = _parse(TS_ROOT, "src/services/orderService.ts")
    second = _parse(TS_ROOT, "src/services/orderService.ts")
    assert [s.id for s in first.symbols] == [s.id for s in second.symbols]
    assert [r.id for r in first.relations] == [r.id for r in second.relations]


def test_registry_dispatches_ts_and_tsx() -> None:
    registry = default_registry()
    assert isinstance(registry.for_path("a.ts"), TypeScriptParser)
    assert isinstance(registry.for_path("a.tsx"), TypeScriptParser)


def test_malformed_typescript_produces_diagnostic_not_crash() -> None:
    result = TypeScriptParser().parse(
        ParseRequest("r", "bad.ts", Language.TYPESCRIPT, b"export class C { m( { ) ")
    )
    assert result.success is False
    assert result.diagnostics
