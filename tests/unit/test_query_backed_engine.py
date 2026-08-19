"""The query-backed parser engine (ADR-0065)."""

from __future__ import annotations

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.query_backed.languages.java import JavaAdapter
from codeatlas.parsing.registry import ParseRequest

SOURCE = b"""package com.shop.orders;

public interface Auditable {
    void audit(String reason);
}

public class OrderService implements Auditable {
    public void audit(String reason) {}
}
"""


def _request(content: bytes = SOURCE) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="src/main/java/com/shop/orders/OrderService.java",
        language="java",
        content=content,
    )


def test_definitions_become_symbols_with_kinds_and_lines() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request())
    assert result.success
    by_name = {symbol.name: symbol for symbol in result.symbols}
    assert by_name["OrderService"].kind is SymbolKind.CLASS
    assert by_name["Auditable"].kind is SymbolKind.INTERFACE
    assert by_name["OrderService"].start_line == 7


def test_an_empty_file_yields_no_symbols_and_still_succeeds() -> None:
    # An empty file has zero lines, so there is no line a symbol could cite;
    # claiming line 1 is invalid evidence and fails snapshot validation.
    result = TagsBackedParser(JavaAdapter()).parse(_request(b""))
    assert result.success
    assert result.symbols == ()


def test_an_oversized_file_is_refused_rather_than_parsed() -> None:
    from codeatlas.parsing.query_backed.engine import MAX_PARSE_BYTES

    result = TagsBackedParser(JavaAdapter()).parse(
        _request(b"a" * (MAX_PARSE_BYTES + 1))
    )
    assert not result.success
    assert [d.code for d in result.diagnostics] == ["PARSE_TOO_LARGE"]


def test_malformed_java_is_reported_not_raised() -> None:
    """Tree-sitter is error-tolerant; the parser must not invent evidence."""
    broken = b"package com.shop; public class { { { void ((("
    result = TagsBackedParser(JavaAdapter()).parse(_request(broken))
    line_count = broken.count(b"\n") + 1
    for symbol in result.symbols:
        assert 1 <= symbol.start_line <= symbol.end_line <= line_count
