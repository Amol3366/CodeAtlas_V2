"""Tests for the Python parser (Blueprint §4.4, Phase 3)."""

from __future__ import annotations

from pathlib import Path

from codeatlas.domain.enums import Language, RelationType, SymbolType
from codeatlas.parsing.contracts import ParseRequest, ParseResult
from codeatlas.parsing.python.parser import PythonParser

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "python_repo"


def _parse(rel: str, *, repo: str = "repo_x") -> ParseResult:
    content = (FIXTURE_ROOT / rel).read_bytes()
    request = ParseRequest(
        repository_id=repo, relative_path=rel, language=Language.PYTHON, content=content
    )
    return PythonParser().parse(request)


def _by_qn(result: ParseResult) -> dict[str, SymbolType]:
    return {s.qualified_name: s.symbol_type for s in result.symbols}


def test_extracts_classes_methods_and_constructor() -> None:
    result = _parse("src/services/payment_service.py")
    symbols = _by_qn(result)
    assert symbols["PaymentService"] is SymbolType.CLASS
    assert symbols["PaymentService.capture"] is SymbolType.METHOD
    assert symbols["PaymentService.refund"] is SymbolType.METHOD
    assert symbols["PaymentService.__init__"] is SymbolType.CONSTRUCTOR


def test_protocol_is_interface_and_methods_captured() -> None:
    symbols = _by_qn(_parse("src/payments/gateway.py"))
    assert symbols["PaymentGateway"] is SymbolType.INTERFACE
    assert symbols["PaymentGateway.charge"] is SymbolType.METHOD
    assert symbols["FakePaymentGateway"] is SymbolType.CLASS


def test_route_decorator_produces_route_symbol() -> None:
    symbols = _by_qn(_parse("src/api/partner_payments.py"))
    assert symbols["capture_partner_payment"] is SymbolType.ROUTE


def test_pytest_functions_are_tests() -> None:
    symbols = _by_qn(_parse("tests/test_payment_service.py"))
    assert symbols["test_capture_returns_transaction_id"] is SymbolType.TEST
    # A non-test helper stays a plain function.
    assert symbols["_service"] is SymbolType.FUNCTION


def test_exact_line_spans_and_signature_and_docstring() -> None:
    result = _parse("src/services/payment_service.py")
    capture = next(s for s in result.symbols if s.qualified_name == "PaymentService.capture")
    assert (capture.start_line, capture.end_line) == (20, 33)
    assert capture.signature is not None and "idempotency_key" in capture.signature
    assert capture.docstring is not None and "Idempotent" in capture.docstring
    assert capture.exported is True


def test_imports_relations_recorded() -> None:
    result = _parse("src/services/payment_service.py")
    imports = {r.target_name for r in result.relations if r.relation_type is RelationType.IMPORTS}
    assert "src.payments.gateway.PaymentGateway" in imports
    assert "src.payments.idempotency.IdempotencyStore" in imports


def test_inherits_relation_recorded() -> None:
    result = _parse("src/services/payment_service.py")
    inherits = {r.target_name for r in result.relations if r.relation_type is RelationType.INHERITS}
    assert "Exception" in inherits  # class PaymentError(Exception)


def test_calls_are_static_resolved_and_may_calls_are_heuristic() -> None:
    result = _parse("tests/test_payment_service.py")
    for rel in result.relations:
        if rel.relation_type is RelationType.CALLS:
            assert rel.confidence == 1.0
            assert rel.derivation.value == "static_resolved"
            assert rel.target_id is not None
        if rel.relation_type is RelationType.MAY_CALL:
            # Invariant CLAUDE.md §2.11: MAY_CALL never certain.
            assert rel.confidence < 1.0
            assert rel.derivation.value != "static_resolved"
    # There is at least one resolved local call (_service()).
    assert any(r.relation_type is RelationType.CALLS for r in result.relations)


def test_contains_relations_link_parent_to_children() -> None:
    result = _parse("src/services/payment_service.py")
    module = next(s for s in result.symbols if s.symbol_type is SymbolType.MODULE)
    contains = [r for r in result.relations if r.relation_type is RelationType.CONTAINS]
    # Module contains the top-level class.
    cls = next(s for s in result.symbols if s.qualified_name == "PaymentService")
    assert any(r.source_id == module.id and r.target_id == cls.id for r in contains)
    # Class contains its method.
    method = next(s for s in result.symbols if s.qualified_name == "PaymentService.capture")
    assert any(r.source_id == cls.id and r.target_id == method.id for r in contains)


def test_parse_is_idempotent() -> None:
    first = _parse("src/services/payment_service.py")
    second = _parse("src/services/payment_service.py")
    assert [s.id for s in first.symbols] == [s.id for s in second.symbols]
    assert [r.id for r in first.relations] == [r.id for r in second.relations]
    assert first.parser_version == PythonParser().version


def test_symbol_ids_are_line_independent() -> None:
    # Prepending blank lines shifts line numbers but must not change symbol ids.
    content = (FIXTURE_ROOT / "src/services/payment_service.py").read_bytes()
    shifted = b"\n\n\n" + content
    base = PythonParser().parse(
        ParseRequest("repo_x", "src/services/payment_service.py", Language.PYTHON, content)
    )
    moved = PythonParser().parse(
        ParseRequest("repo_x", "src/services/payment_service.py", Language.PYTHON, shifted)
    )
    assert {s.id for s in base.symbols} == {s.id for s in moved.symbols}
