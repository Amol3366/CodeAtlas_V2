"""Python reference extraction: only what the syntax states outright."""

from __future__ import annotations

from pathlib import Path

from codeatlas.contracts import RelationKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import ParseRequest, ParseResult

FIXTURE = Path("tests/evaluation/cases/fixtures/python_app/src/payments/service.py")


def _parse(source: str, relative_path: str = "src/payments/service.py") -> ParseResult:
    return PythonParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id="file_1",
            relative_path=relative_path,
            language="python",
            content=source.encode("utf-8"),
        )
    )


def _kinds(
    references: tuple[SymbolReference, ...], kind: RelationKind
) -> list[SymbolReference]:
    return [item for item in references if item.kind is kind]


def _hints(references: tuple[SymbolReference, ...], kind: RelationKind) -> set[str]:
    return {item.target_hint for item in _kinds(references, kind)}


def test_the_fixture_produces_its_declared_reference_set() -> None:
    result = _parse(FIXTURE.read_text(encoding="utf-8"))

    assert result.success is True
    imports = _kinds(result.references, RelationKind.IMPORTS)
    assert len(imports) == 1
    assert imports[0].target_hint == "IdempotencyStore"
    assert imports[0].module_hint == ".idempotency"
    assert imports[0].start_line == 1

    calls = {
        (item.target_hint, item.module_hint, item.start_line)
        for item in _kinds(result.references, RelationKind.CALLS)
    }
    assert ("claim", "self.store", 10) in calls
    assert ("ValueError", "", 9) in calls


def test_a_call_records_its_enclosing_symbol_as_the_source() -> None:
    result = _parse(FIXTURE.read_text(encoding="utf-8"))
    parsed = {symbol.qualified_name: symbol.symbol_id for symbol in result.symbols}

    (claim,) = [
        item
        for item in result.references
        if item.kind is RelationKind.CALLS and item.target_hint == "claim"
    ]

    assert claim.source_symbol_id == parsed["PaymentService.capture"]


def test_an_import_is_attributed_to_the_module(create_module: None = None) -> None:
    result = _parse(FIXTURE.read_text(encoding="utf-8"))
    parsed = {symbol.qualified_name: symbol.symbol_id for symbol in result.symbols}

    (imported,) = _kinds(result.references, RelationKind.IMPORTS)

    assert imported.source_symbol_id == parsed["src.payments.service"]


def test_nesting_produces_contains_references() -> None:
    result = _parse(FIXTURE.read_text(encoding="utf-8"))

    contains = _hints(result.references, RelationKind.CONTAINS)

    assert contains == {
        "PaymentService",
        "PaymentService.__init__",
        "PaymentService.capture",
    }


def test_a_base_class_produces_an_inherits_reference() -> None:
    result = _parse("class Child(Base):\n    pass\n")

    assert _hints(result.references, RelationKind.INHERITS) == {"Base"}


def test_a_dotted_base_class_keeps_its_receiver_as_a_hint() -> None:
    result = _parse("class Child(mod.Base):\n    pass\n")

    (inherits,) = _kinds(result.references, RelationKind.INHERITS)
    assert inherits.target_hint == "Base"
    assert inherits.module_hint == "mod"


def test_a_self_call_resolves_its_receiver_from_the_enclosing_class() -> None:
    """`self` is the one receiver whose type is known without inference."""
    result = _parse(
        "class Service:\n"
        "    def run(self):\n"
        "        return self.helper()\n"
        "    def helper(self):\n"
        "        return 1\n"
    )

    (call,) = _kinds(result.references, RelationKind.CALLS)
    assert call.target_hint == "Service.helper"


def test_an_attribute_call_carries_the_receiver_without_assuming_its_type() -> None:
    result = _parse("def run(store):\n    return store.claim(1)\n")

    (call,) = _kinds(result.references, RelationKind.CALLS)
    assert call.target_hint == "claim"
    assert call.module_hint == "store"


def test_annotations_produce_type_references() -> None:
    result = _parse("def run(value: Widget) -> Gadget:\n    return value\n")

    assert _hints(result.references, RelationKind.REFERENCES) == {"Widget", "Gadget"}


def test_a_none_return_annotation_is_not_a_type_reference() -> None:
    """`-> None` names no type worth citing; emitting it would be pure noise."""
    result = _parse("def run() -> None:\n    return None\n")

    assert _kinds(result.references, RelationKind.REFERENCES) == []


def test_dunder_all_produces_exports() -> None:
    result = _parse('__all__ = ["alpha", "beta"]\n')

    assert _hints(result.references, RelationKind.EXPORTS) == {"alpha", "beta"}


def test_a_non_literal_export_entry_is_not_invented() -> None:
    result = _parse("__all__ = [NAME]\n")

    assert _kinds(result.references, RelationKind.EXPORTS) == []


# --- The "not emitted" list. Each gap is counted, never guessed. --------------


def test_a_call_through_a_computed_callee_produces_no_reference() -> None:
    result = _parse("def run(handlers):\n    return handlers[0]()\n")

    assert _kinds(result.references, RelationKind.CALLS) == []


def test_a_computed_call_is_reported_as_a_diagnostic() -> None:
    """The gap must be visible, not silent."""
    result = _parse("def run(handlers):\n    return handlers[0]()\n")

    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "REFERENCE_DYNAMIC_CALL" in codes


def test_getattr_produces_no_call_reference() -> None:
    result = _parse("def run(obj):\n    return getattr(obj, 'name')()\n")

    assert _hints(result.references, RelationKind.CALLS) == set()
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "REFERENCE_DYNAMIC_ATTRIBUTE" in codes


def test_a_star_import_records_no_target() -> None:
    result = _parse("from alpha import *\n")

    assert _kinds(result.references, RelationKind.IMPORTS) == []
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "REFERENCE_STAR_IMPORT" in codes


def test_a_dynamic_import_records_no_target() -> None:
    result = _parse(
        "import importlib\n\ndef run():\n    importlib.import_module('x')\n"
    )

    assert "x" not in _hints(result.references, RelationKind.IMPORTS)
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "REFERENCE_DYNAMIC_IMPORT" in codes


# --- Structural properties ----------------------------------------------------


def test_extraction_is_a_pure_function_of_the_file() -> None:
    source = FIXTURE.read_text(encoding="utf-8")

    first = _parse(source).references
    second = _parse(source).references

    assert first == second


def test_two_identical_calls_on_one_line_are_both_recorded() -> None:
    """`f(f(x))` is two real edges; `part` is what keeps them distinct."""
    result = _parse("def run(x):\n    return f(f(x))\n")

    calls = _kinds(result.references, RelationKind.CALLS)
    assert len(calls) == 2
    assert {item.part for item in calls} == {0, 1}


def test_a_call_nested_in_callee_position_is_still_recorded() -> None:
    """`foo().bar()` really does call `foo`; descending into the callee finds it."""
    result = _parse("def run():\n    return foo().bar()\n")

    assert _hints(result.references, RelationKind.CALLS) == {"foo", "bar"}


def test_every_reference_cites_a_real_line() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    line_count = len(source.splitlines())

    for reference in _parse(source).references:
        assert 1 <= reference.start_line <= line_count
        assert reference.start_line <= reference.end_line <= line_count


def test_a_malformed_file_yields_no_references(tmp_path: Path) -> None:
    """A broken tree must not produce a partial reference set."""
    result = _parse("def broken(:\n    pass\n")

    assert result.success is False
    assert result.references == ()


def test_a_file_with_no_references_produces_none() -> None:
    result = _parse("VALUE = 1\n")

    assert _kinds(result.references, RelationKind.CALLS) == []
    assert _kinds(result.references, RelationKind.IMPORTS) == []


# --- CONSUMES_FIXTURE: one reference per injected test parameter --------------


def fixture_references(
    source: str, path: str = "test_orders.py"
) -> list[SymbolReference]:
    result = _parse(source, relative_path=path)
    return _kinds(result.references, RelationKind.CONSUMES_FIXTURE)


def test_a_test_parameter_becomes_a_fixture_reference() -> None:
    source = "def test_orders(store):\n    assert store\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [(ref.target_hint, ref.module_hint) for ref in refs] == [("store", "")]


def test_each_parameter_becomes_its_own_reference() -> None:
    source = "def test_orders(store, clock):\n    assert store and clock\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [ref.target_hint for ref in refs] == ["store", "clock"]


def test_parameters_on_one_line_get_distinct_parts() -> None:
    # `part` is what keeps two references on the same line apart.
    source = "def test_orders(store, clock):\n    assert store and clock\n"
    refs = fixture_references(source, path="test_orders.py")
    assert len({ref.part for ref in refs}) == 2


def test_a_defaulted_parameter_is_not_injected() -> None:
    # pytest does not inject a parameter that already has a value.
    source = "def test_orders(store, limit=5):\n    assert store and limit\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [ref.target_hint for ref in refs] == ["store"]


def test_varargs_and_kwargs_are_not_injected() -> None:
    source = "def test_orders(store, *args, **kwargs):\n    assert store\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [ref.target_hint for ref in refs] == ["store"]


def test_self_and_cls_are_not_injected() -> None:
    source = (
        "class TestOrders:\n"
        "    def test_orders(self, store):\n"
        "        assert store\n"
    )
    refs = fixture_references(source, path="test_orders.py")
    assert "self" not in [ref.target_hint for ref in refs]


def test_a_non_test_function_emits_no_fixture_reference() -> None:
    source = "def build_orders(store):\n    return store\n"
    refs = fixture_references(source, path="test_orders.py")
    assert refs == []
