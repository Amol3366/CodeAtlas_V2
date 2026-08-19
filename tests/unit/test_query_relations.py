"""References emitted by the query-backed engine (ADR-0065)."""

from __future__ import annotations

from codeatlas.contracts import RelationKind
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.query_backed.languages.java import JavaAdapter
from codeatlas.parsing.registry import ParseRequest, default_registry

SOURCE = b"""package com.shop.orders;

import com.shop.payments.PaymentService;

public class OrderService implements Auditable {
    private PaymentService payments;
    public void capture(String orderId) {
        payments.charge(orderId);
    }
}
"""


def _request() -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="src/main/java/com/shop/orders/OrderService.java",
        language="java",
        content=SOURCE,
    )


def test_java_is_registered_in_the_default_registry() -> None:
    assert default_registry().parser_for("java") is not None


def test_imports_calls_and_implements_are_all_emitted() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request())
    kinds = {(ref.kind, ref.target_hint) for ref in result.references}
    assert (RelationKind.IMPORTS, "PaymentService") in kinds
    assert (RelationKind.CALLS, "charge") in kinds
    assert (RelationKind.IMPLEMENTS, "Auditable") in kinds


def test_every_reference_cites_a_line_inside_the_file() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request())
    line_count = SOURCE.count(b"\n") + 1
    assert result.references
    for ref in result.references:
        assert 1 <= ref.start_line <= ref.end_line <= line_count
