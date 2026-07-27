"""TypeScript and JavaScript symbol extraction, Tree-sitter only."""

from __future__ import annotations

from pathlib import Path

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.registry import ParseRequest, ParseResult, default_registry
from codeatlas.parsing.tsjs_parser import TsJsParser

FIXTURES = Path("tests/evaluation/cases/fixtures/tsjs_app/src")


def _parse(source: str, relative_path: str) -> ParseResult:
    language = "typescript" if relative_path.endswith((".ts", ".tsx")) else "javascript"
    return TsJsParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id="file_1",
            relative_path=relative_path,
            language=language,
            content=source.encode("utf-8"),
        )
    )


def _by_name(result: ParseResult) -> dict[str, tuple[SymbolKind, int, int]]:
    return {
        symbol.qualified_name: (symbol.kind, symbol.start_line, symbol.end_line)
        for symbol in result.symbols
    }


def test_the_typescript_fixture_produces_its_declared_symbols() -> None:
    result = _parse(
        (FIXTURES / "orders.ts").read_text(encoding="utf-8"), "src/orders.ts"
    )

    assert result.success is True
    symbols = _by_name(result)
    assert symbols["src.orders"][0] is SymbolKind.MODULE
    assert symbols["Order"] == (SymbolKind.INTERFACE, 1, 3)
    assert symbols["total"] == (SymbolKind.FUNCTION, 5, 7)


def test_the_javascript_fixture_produces_its_declared_symbols() -> None:
    result = _parse(
        (FIXTURES / "client.js").read_text(encoding="utf-8"), "src/client.js"
    )

    assert result.success is True
    symbols = _by_name(result)
    assert symbols["src.client"][0] is SymbolKind.MODULE
    assert symbols["render"] == (SymbolKind.FUNCTION, 3, 5)


def test_an_exported_declaration_range_includes_the_export_keyword() -> None:
    """A reader asking where `Order` is defined expects to see `export`."""
    result = _parse("export interface Order {\n  id: string;\n}\n", "src/a.ts")

    symbols = _by_name(result)
    assert symbols["Order"][1] == 1


def test_a_class_and_its_members_are_qualified_by_their_container() -> None:
    result = _parse(
        "export class Service {\n"
        "  constructor(store) { this.store = store; }\n"
        "  run(key) { return key; }\n"
        "}\n",
        "src/service.ts",
    )

    symbols = _by_name(result)
    assert symbols["Service"][0] is SymbolKind.CLASS
    assert symbols["Service.constructor"][0] is SymbolKind.CONSTRUCTOR
    assert symbols["Service.run"][0] is SymbolKind.METHOD


def test_supported_declaration_kinds_map_onto_existing_symbol_kinds() -> None:
    result = _parse(
        "type Id = string;\n"
        "enum Color { Red }\n"
        "interface Shape { area(): number }\n"
        "export const LIMIT = 10;\n"
        "export const handler = (x) => x;\n",
        "src/kinds.ts",
    )

    symbols = _by_name(result)
    assert symbols["Id"][0] is SymbolKind.TYPE_ALIAS
    assert symbols["Color"][0] is SymbolKind.ENUM
    assert symbols["Shape"][0] is SymbolKind.INTERFACE
    assert symbols["LIMIT"][0] is SymbolKind.CONSTANT
    assert symbols["handler"][0] is SymbolKind.FUNCTION


def test_a_class_field_is_a_field_symbol() -> None:
    result = _parse(
        "class Service {\n  limit: number = 3;\n}\n",
        "src/service.ts",
    )

    assert _by_name(result)["Service.limit"][0] is SymbolKind.FIELD


def test_visibility_follows_naming_and_modifiers() -> None:
    result = _parse(
        "class Service {\n"
        "  private hidden() { return 1; }\n"
        "  _byConvention() { return 2; }\n"
        "  open() { return 3; }\n"
        "}\n",
        "src/service.ts",
    )

    visibility = {symbol.qualified_name: symbol.visibility for symbol in result.symbols}
    assert visibility["Service.hidden"] == "private"
    assert visibility["Service._byConvention"] == "private"
    assert visibility["Service.open"] == "public"


def test_a_tsx_file_uses_the_tsx_grammar() -> None:
    """Plain TS cannot parse JSX; falling back to it would silently lose symbols."""
    result = _parse(
        "export const View = () => <div className='x' />;\n", "src/view.tsx"
    )

    assert result.success is True
    assert "View" in _by_name(result)


def test_jsx_in_a_plain_ts_file_is_reported_rather_than_silently_wrong() -> None:
    result = _parse("const View = () => <div />;\n", "src/view.ts")

    assert result.success is False
    assert {item.code for item in result.diagnostics} == {"PARSE_SYNTAX_ERROR"}


def test_a_malformed_file_recovers_what_it_can() -> None:
    result = _parse("export function broken( {\n", "src/broken.ts")

    assert result.success is False
    assert result.diagnostics != ()


def test_the_registry_routes_typescript_and_javascript() -> None:
    registry = default_registry()

    assert registry.parser_for("typescript") is not None
    assert registry.parser_for("javascript") is not None
    assert registry.parser_for("python") is not None


def test_parsing_is_deterministic() -> None:
    source = (FIXTURES / "orders.ts").read_text(encoding="utf-8")

    first = _parse(source, "src/orders.ts").symbols
    second = _parse(source, "src/orders.ts").symbols

    assert first == second


def test_every_symbol_cites_a_real_line() -> None:
    source = (FIXTURES / "orders.ts").read_text(encoding="utf-8")
    line_count = len(source.splitlines())

    for symbol in _parse(source, "src/orders.ts").symbols:
        assert 1 <= symbol.start_line <= line_count
        assert symbol.start_line <= symbol.end_line <= line_count


def test_an_empty_file_has_no_symbols() -> None:
    """Same rule as the Python parser: zero lines, nothing to cite."""
    result = TsJsParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id="file_1",
            relative_path="src/empty.ts",
            language="typescript",
            content=b"",
        )
    )
    assert result.success
    assert result.symbols == ()
