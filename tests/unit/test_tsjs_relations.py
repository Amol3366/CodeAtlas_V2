"""TypeScript and JavaScript reference extraction."""

from __future__ import annotations

from pathlib import Path

from codeatlas.contracts import RelationKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.parsing.registry import ParseRequest, ParseResult
from codeatlas.parsing.tsjs_parser import TsJsParser

FIXTURES = Path("tests/evaluation/cases/fixtures/tsjs_app/src")


def _parse(source: str, relative_path: str = "src/a.ts") -> ParseResult:
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


def _kinds(
    references: tuple[SymbolReference, ...], kind: RelationKind
) -> list[SymbolReference]:
    return [item for item in references if item.kind is kind]


def _hints(references: tuple[SymbolReference, ...], kind: RelationKind) -> set[str]:
    return {item.target_hint for item in _kinds(references, kind)}


# --- The four edges the corpus declares for `tsjs_app` -------------------------


def test_client_imports_total_from_orders() -> None:
    result = _parse(
        (FIXTURES / "client.js").read_text(encoding="utf-8"), "src/client.js"
    )

    (imported,) = _kinds(result.references, RelationKind.IMPORTS)
    assert imported.target_hint == "total"
    assert imported.module_hint == "./orders"


def test_render_calls_total() -> None:
    result = _parse(
        (FIXTURES / "client.js").read_text(encoding="utf-8"), "src/client.js"
    )

    assert "total" in _hints(result.references, RelationKind.CALLS)


def test_orders_exports_its_interface_and_function() -> None:
    result = _parse(
        (FIXTURES / "orders.ts").read_text(encoding="utf-8"), "src/orders.ts"
    )

    assert {"Order", "total"} <= _hints(result.references, RelationKind.EXPORTS)


def test_total_references_the_order_type() -> None:
    result = _parse(
        (FIXTURES / "orders.ts").read_text(encoding="utf-8"), "src/orders.ts"
    )

    assert "Order" in _hints(result.references, RelationKind.REFERENCES)


# --- Import and export forms --------------------------------------------------


def test_a_default_import_is_recorded_as_default() -> None:
    result = _parse('import Widget from "./widget";\n')

    (imported,) = _kinds(result.references, RelationKind.IMPORTS)
    assert imported.target_hint == "default"
    assert imported.module_hint == "./widget"


def test_a_namespace_import_records_the_module() -> None:
    result = _parse('import * as ns from "./ns";\n')

    (imported,) = _kinds(result.references, RelationKind.IMPORTS)
    assert imported.module_hint == "./ns"


def test_a_bare_specifier_is_recorded_verbatim() -> None:
    """No node_modules lookup ever happens; the specifier is just text."""
    result = _parse('import React from "react";\n')

    (imported,) = _kinds(result.references, RelationKind.IMPORTS)
    assert imported.module_hint == "react"


def test_a_named_export_clause_records_each_name() -> None:
    result = _parse("const a = 1;\nconst b = 2;\nexport { a, b };\n")

    assert {"a", "b"} <= _hints(result.references, RelationKind.EXPORTS)


def test_an_export_default_is_recorded_as_default() -> None:
    result = _parse("class C {}\nexport default C;\n")

    assert "default" in _hints(result.references, RelationKind.EXPORTS)


# --- Heritage -----------------------------------------------------------------


def test_extends_produces_an_inherits_reference() -> None:
    result = _parse("class C extends B {}\n")

    assert _hints(result.references, RelationKind.INHERITS) == {"B"}


def test_implements_produces_an_implements_reference() -> None:
    result = _parse("class C implements I {}\n")

    assert _hints(result.references, RelationKind.IMPLEMENTS) == {"I"}


# --- Calls --------------------------------------------------------------------


def test_a_bare_call_records_the_name() -> None:
    result = _parse("function run() { return total(1); }\n")

    (call,) = _kinds(result.references, RelationKind.CALLS)
    assert call.target_hint == "total"
    assert call.module_hint == ""


def test_a_member_call_carries_the_receiver_without_assuming_its_type() -> None:
    result = _parse("function run(o) { return o.m(1); }\n")

    (call,) = _kinds(result.references, RelationKind.CALLS)
    assert call.target_hint == "m"
    assert call.module_hint == "o"


def test_a_this_call_resolves_its_receiver_from_the_enclosing_class() -> None:
    result = _parse(
        "class Service {\n"
        "  run() { return this.helper(); }\n"
        "  helper() { return 1; }\n"
        "}\n"
    )

    calls = _kinds(result.references, RelationKind.CALLS)
    assert [item.target_hint for item in calls] == ["Service.helper"]


def test_a_computed_callee_produces_no_call_reference() -> None:
    result = _parse("function run(hs) { return hs[0](); }\n")

    assert _kinds(result.references, RelationKind.CALLS) == []
    codes = {item.code for item in result.diagnostics}
    assert "REFERENCE_DYNAMIC_CALL" in codes


# --- Types --------------------------------------------------------------------


def test_a_parameter_annotation_produces_a_type_reference() -> None:
    result = _parse("function run(o: Order): number { return 1; }\n")

    assert "Order" in _hints(result.references, RelationKind.REFERENCES)


def test_a_new_expression_references_its_constructor() -> None:
    result = _parse("function run() { return new Widget(); }\n")

    assert "Widget" in _hints(result.references, RelationKind.REFERENCES)


# --- Structure and Windows behavior -------------------------------------------


def test_nesting_produces_contains_references() -> None:
    result = _parse("export class C {\n  run() { return 1; }\n}\n")

    assert {"C", "C.run"} <= _hints(result.references, RelationKind.CONTAINS)


def test_a_specifier_keeps_its_case_exactly_as_written() -> None:
    """Case-only mismatches must stay detectable, not be normalized away.

    A case-insensitive Windows filesystem would otherwise let the same
    repository resolve differently than it does on Linux.
    """
    result = _parse('import { total } from "./Orders";\n')

    (imported,) = _kinds(result.references, RelationKind.IMPORTS)
    assert imported.module_hint == "./Orders"


def test_extraction_is_a_pure_function_of_the_file() -> None:
    source = (FIXTURES / "orders.ts").read_text(encoding="utf-8")

    assert _parse(source, "src/orders.ts").references == (
        _parse(source, "src/orders.ts").references
    )


def test_every_reference_cites_a_real_line() -> None:
    source = (FIXTURES / "orders.ts").read_text(encoding="utf-8")
    line_count = len(source.splitlines())

    for reference in _parse(source, "src/orders.ts").references:
        assert 1 <= reference.start_line <= line_count
        assert reference.start_line <= reference.end_line <= line_count


def test_a_malformed_file_yields_no_references() -> None:
    result = _parse("export function broken( {\n")

    assert result.success is False
    assert result.references == ()
