"""Tests for the JavaScript parser (Blueprint §4.4, Phase 4)."""

from __future__ import annotations

from codeatlas.domain.enums import Language, RelationType, SymbolType
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.javascript.parser import JavaScriptParser
from codeatlas.parsing.registry import default_registry

_SOURCE = b"""import { A } from './a.js';

export function greet(name) {
  return helper(name);
}

function helper(n) {
  return n;
}

export class Widget {
  render() {
    return 1;
  }
}

const build = () => greet('x');
"""


def _parse(source: bytes = _SOURCE, path: str = "src/w.js") -> object:
    return JavaScriptParser().parse(ParseRequest("repo_x", path, Language.JAVASCRIPT, source))


def test_functions_classes_methods_and_arrow_consts() -> None:
    result = _parse()
    by_qn = {s.qualified_name: s.symbol_type for s in result.symbols}  # type: ignore[attr-defined]
    assert by_qn["greet"] is SymbolType.FUNCTION
    assert by_qn["helper"] is SymbolType.FUNCTION
    assert by_qn["Widget"] is SymbolType.CLASS
    assert by_qn["Widget.render"] is SymbolType.METHOD
    assert by_qn["build"] is SymbolType.FUNCTION  # arrow assigned to a name


def test_export_flag() -> None:
    result = _parse()
    exported = {s.qualified_name for s in result.symbols if s.exported}  # type: ignore[attr-defined]
    assert "greet" in exported
    assert "Widget" in exported
    assert "helper" not in exported  # not exported


def test_local_call_is_static_resolved() -> None:
    result = _parse()
    calls = [
        r
        for r in result.relations
        if r.relation_type is RelationType.CALLS  # type: ignore[attr-defined]
    ]
    assert any(r.target_name == "helper" and r.confidence == 1.0 for r in calls)


def test_registry_dispatches_js_variants() -> None:
    registry = default_registry()
    for ext in ("a.js", "a.jsx", "a.mjs", "a.cjs"):
        assert isinstance(registry.for_path(ext), JavaScriptParser)


def test_malformed_javascript_produces_diagnostic_not_crash() -> None:
    result = _parse(b"function ( { ) )) class", "bad.js")
    assert result.success is False  # type: ignore[attr-defined]
    assert result.diagnostics  # type: ignore[attr-defined]
