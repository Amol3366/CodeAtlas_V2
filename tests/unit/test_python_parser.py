"""Python symbol extraction through Tree-sitter plus `ast`."""

from __future__ import annotations

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import ParseRequest, ParserRegistry, default_registry

SERVICE_SOURCE = (
    b"from .idempotency import IdempotencyStore\n"
    b"\n"
    b"class PaymentService:\n"
    b"    def __init__(self, store: IdempotencyStore) -> None:\n"
    b"        self.store = store\n"
    b"\n"
    b"    def capture(self, key: str) -> str:\n"
    b"        return self.store.claim(key)\n"
)


def _request(content: bytes, path: str = "src/payments/service.py") -> ParseRequest:
    return ParseRequest(
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_id="file_1",
        relative_path=path,
        language="python",
        content=content,
    )


def test_extracts_class_method_and_constructor_with_exact_lines() -> None:
    result = PythonParser().parse(_request(SERVICE_SOURCE))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert result.success is True
    assert by_name["PaymentService"].kind is SymbolKind.CLASS
    assert (
        by_name["PaymentService"].start_line,
        by_name["PaymentService"].end_line,
    ) == (3, 8)
    assert by_name["PaymentService.capture"].kind is SymbolKind.METHOD
    assert (
        by_name["PaymentService.capture"].start_line,
        by_name["PaymentService.capture"].end_line,
    ) == (7, 8)
    assert by_name["PaymentService.__init__"].kind is SymbolKind.CONSTRUCTOR


def test_emits_a_module_symbol_with_the_dotted_module_path() -> None:
    result = PythonParser().parse(_request(SERVICE_SOURCE))
    module = next(s for s in result.symbols if s.kind is SymbolKind.MODULE)
    assert module.module_path == "src.payments.service"
    assert module.qualified_name == "src.payments.service"
    assert module.start_line == 1
    assert module.end_line == 8


def test_package_init_module_path_drops_the_init_suffix() -> None:
    result = PythonParser().parse(_request(b"VALUE = 1\n", "src/payments/__init__.py"))
    module = next(s for s in result.symbols if s.kind is SymbolKind.MODULE)
    assert module.module_path == "src.payments"


def test_module_level_function_and_constant_are_extracted() -> None:
    source = b"MAX_RETRIES = 3\n\ndef load() -> int:\n    return MAX_RETRIES\n"
    result = PythonParser().parse(_request(source, "src/util.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["MAX_RETRIES"].kind is SymbolKind.CONSTANT
    assert by_name["load"].kind is SymbolKind.FUNCTION


def test_test_functions_in_test_files_are_marked_as_tests() -> None:
    source = b"def test_capture() -> None:\n    assert True\n"
    result = PythonParser().parse(_request(source, "tests/test_service.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["test_capture"].kind is SymbolKind.TEST


def test_test_prefixed_function_outside_a_test_file_stays_a_function() -> None:
    source = b"def test_capture() -> None:\n    assert True\n"
    result = PythonParser().parse(_request(source, "src/util.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["test_capture"].kind is SymbolKind.FUNCTION


def test_async_function_is_extracted() -> None:
    source = b"async def fetch() -> int:\n    return 1\n"
    result = PythonParser().parse(_request(source, "src/util.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["fetch"].kind is SymbolKind.FUNCTION


def test_decorated_function_range_starts_at_the_decorator() -> None:
    source = b"import functools\n\n@functools.cache\ndef load() -> int:\n    return 1\n"
    result = PythonParser().parse(_request(source, "src/util.py"))
    load = next(s for s in result.symbols if s.qualified_name == "load")
    assert (load.start_line, load.end_line) == (3, 5)


def test_nested_class_produces_a_dotted_qualified_name() -> None:
    source = (
        b"class Outer:\n"
        b"    class Inner:\n"
        b"        def run(self) -> None:\n"
        b"            return None\n"
    )
    result = PythonParser().parse(_request(source, "src/util.py"))
    names = {symbol.qualified_name for symbol in result.symbols}
    assert "Outer.Inner" in names
    assert "Outer.Inner.run" in names


def test_visibility_is_private_for_underscore_names() -> None:
    source = b"class _Hidden:\n    def _helper(self) -> None:\n        return None\n"
    result = PythonParser().parse(_request(source, "src/util.py"))
    hidden = next(s for s in result.symbols if s.qualified_name == "_Hidden")
    helper = next(s for s in result.symbols if s.qualified_name == "_Hidden._helper")
    assert hidden.visibility == "private"
    assert helper.visibility == "private"


def test_signature_is_captured_for_functions() -> None:
    result = PythonParser().parse(_request(SERVICE_SOURCE))
    capture = next(
        s for s in result.symbols if s.qualified_name == "PaymentService.capture"
    )
    assert capture.signature is not None
    assert "key" in capture.signature


def test_byte_range_matches_the_definition_source() -> None:
    result = PythonParser().parse(_request(SERVICE_SOURCE))
    capture = next(
        s for s in result.symbols if s.qualified_name == "PaymentService.capture"
    )
    excerpt = SERVICE_SOURCE[capture.start_byte : capture.end_byte].decode("utf-8")
    assert excerpt.startswith("def capture")
    assert excerpt.rstrip().endswith("claim(key)")


def test_symbol_ids_are_stable_across_repeated_parses() -> None:
    first = PythonParser().parse(_request(SERVICE_SOURCE))
    second = PythonParser().parse(_request(SERVICE_SOURCE))
    assert [s.symbol_id for s in first.symbols] == [s.symbol_id for s in second.symbols]
    assert [s.symbol_version_id for s in first.symbols] == [
        s.symbol_version_id for s in second.symbols
    ]


def test_editing_a_body_changes_the_version_but_not_the_symbol_id() -> None:
    edited = SERVICE_SOURCE.replace(b"claim(key)", b"claim(key.strip())")
    original = PythonParser().parse(_request(SERVICE_SOURCE))
    changed = PythonParser().parse(_request(edited))
    before = next(
        s for s in original.symbols if s.qualified_name == "PaymentService.capture"
    )
    after = next(
        s for s in changed.symbols if s.qualified_name == "PaymentService.capture"
    )
    assert before.symbol_id == after.symbol_id
    assert before.symbol_version_id != after.symbol_version_id


def test_utf8_bom_source_parses_with_correct_lines_and_bytes() -> None:
    # Windows editors and PowerShell's `Set-Content -Encoding utf8` write a BOM.
    # A byte-order mark must not make a valid file unparsable.
    source = b"\xef\xbb\xbf" + SERVICE_SOURCE
    result = PythonParser().parse(_request(source))
    assert result.success is True
    assert result.diagnostics == ()

    capture = next(
        s for s in result.symbols if s.qualified_name == "PaymentService.capture"
    )
    assert (capture.start_line, capture.end_line) == (7, 8)
    excerpt = source[capture.start_byte : capture.end_byte].decode("utf-8")
    assert excerpt.startswith("def capture")


def test_malformed_source_yields_diagnostics_not_an_exception() -> None:
    result = PythonParser().parse(_request(b"def broken(:\n    pass\n", "src/bad.py"))
    assert result.success is False
    assert any(d.code == "PARSE_SYNTAX_ERROR" for d in result.diagnostics)


def test_malformed_source_still_recovers_symbols_through_tree_sitter() -> None:
    source = b"class Good:\n    pass\n\ndef broken(:\n    pass\n"
    result = PythonParser().parse(_request(source, "src/bad.py"))
    assert result.success is False
    assert any(symbol.qualified_name == "Good" for symbol in result.symbols)


def test_oversized_content_is_rejected_without_parsing() -> None:
    result = PythonParser().parse(_request(b"x = 1\n" + b"# pad\n" * 400_000))
    assert result.success is False
    assert [d.code for d in result.diagnostics] == ["PARSE_TOO_LARGE"]
    assert result.symbols == ()


def test_undecodable_content_is_reported() -> None:
    result = PythonParser().parse(_request(b"\xff\xfe\x00invalid", "src/bad.py"))
    assert result.success is False
    assert any(d.code == "PARSE_DECODE_ERROR" for d in result.diagnostics)


def test_registry_resolves_python_and_ignores_unsupported_languages() -> None:
    # Phase 3 added TypeScript and JavaScript, so this test no longer asserts
    # that `typescript` is unsupported — that was Phase 1's truth, not a
    # contract. It still asserts the property that matters: a language nobody
    # registered resolves to nothing rather than to an arbitrary parser.
    #
    # ADR-0065 then registered Rust, and this line had used `rust` as its
    # example of an unregistered language — the same staleness the paragraph
    # above records for `typescript`, recurring for the same reason. `kotlin`
    # is the example now precisely because ADR-0065 measured its grammar as
    # shipping no `tags.scm`, so it cannot be registered by this engine.
    registry = default_registry()
    parser = registry.parser_for("python")
    assert parser is not None
    assert parser.name == "python"
    assert registry.parser_for("kotlin") is None


def test_registry_rejects_a_duplicate_language() -> None:
    registry = ParserRegistry()
    registry.register(PythonParser())
    try:
        registry.register(PythonParser())
    except ValueError:
        return
    raise AssertionError("registering a duplicate language should fail")


def test_a_bare_pytest_fixture_is_a_fixture_symbol() -> None:
    source = b"import pytest\n\n@pytest.fixture\ndef store():\n    return 1\n"
    result = PythonParser().parse(_request(source, "conftest.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["store"].kind is SymbolKind.FIXTURE


def test_a_called_pytest_fixture_is_a_fixture_symbol() -> None:
    source = (
        b'import pytest\n\n@pytest.fixture(scope="session")\n'
        b"def store():\n    return 1\n"
    )
    result = PythonParser().parse(_request(source, "conftest.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["store"].kind is SymbolKind.FIXTURE


def test_a_bare_imported_fixture_name_is_a_fixture_symbol() -> None:
    source = b"from pytest import fixture\n\n@fixture\ndef store():\n    return 1\n"
    result = PythonParser().parse(_request(source, "conftest.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["store"].kind is SymbolKind.FIXTURE


def test_a_decorated_test_function_stays_a_test() -> None:
    # pytest collects this as a test. The TEST branch must win.
    source = b"import pytest\n\n@pytest.fixture\ndef test_store():\n    return 1\n"
    result = PythonParser().parse(_request(source, "test_orders.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["test_store"].kind is SymbolKind.TEST


def test_an_undecorated_function_in_a_test_file_is_a_function() -> None:
    source = b"def build_store():\n    return 1\n"
    result = PythonParser().parse(_request(source, "conftest.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["build_store"].kind is SymbolKind.FUNCTION


def test_a_string_naming_pytest_fixture_classifies_nothing() -> None:
    # Matching reads the AST decorator name, never source text.
    source = (
        b'def store():\n    """Use pytest.fixture for this."""\n    return 1\n'
    )
    result = PythonParser().parse(_request(source, "conftest.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["store"].kind is SymbolKind.FUNCTION


def test_an_unrelated_decorator_does_not_make_a_fixture() -> None:
    source = b"import functools\n\n@functools.cache\ndef store():\n    return 1\n"
    result = PythonParser().parse(_request(source, "conftest.py"))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert by_name["store"].kind is SymbolKind.FUNCTION


def test_an_empty_file_has_no_symbols() -> None:
    """An empty `__init__.py` has zero lines, so there is nothing to cite: a
    module symbol claiming line 1 would be invalid evidence and fails
    snapshot validation."""
    result = PythonParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id="file_1",
            relative_path="src/pkg/__init__.py",
            language="python",
            content=b"",
        )
    )
    assert result.success
    assert result.symbols == ()
