"""Indexing a Java repository end to end (ADR-0065).

The unit tests prove the parser produces symbols from bytes. This proves the
whole pipeline accepts them: classification routes the file to the query-backed
parser, extraction stores the symbols, and snapshot validation accepts their
ranges.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import SymbolKind
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

ORDER_SERVICE = """package com.shop.orders;

import com.shop.payments.PaymentService;

public class OrderService {
    private final PaymentService payments;

    public OrderService(PaymentService payments) {
        this.payments = payments;
    }

    public void capture(String orderId) {
        payments.charge(orderId);
    }
}
"""

PAYMENT_SERVICE = """package com.shop.payments;

public class PaymentService {
    public void charge(String orderId) {
    }
}
"""


@dataclass
class JavaHarness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    root: Path


@pytest.fixture()
def java_harness(tmp_path: Path) -> Iterator[JavaHarness]:
    root = tmp_path / "java_app"
    orders = root / "src" / "main" / "java" / "com" / "shop" / "orders"
    payments = root / "src" / "main" / "java" / "com" / "shop" / "payments"
    orders.mkdir(parents=True)
    payments.mkdir(parents=True)
    (orders / "OrderService.java").write_text(ORDER_SERVICE, encoding="utf-8")
    (payments / "PaymentService.java").write_text(PAYMENT_SERVICE, encoding="utf-8")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        yield JavaHarness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=root,
        )


def _symbols(harness: JavaHarness) -> dict[str, SymbolKind]:
    """Qualified name to kind for the active snapshot.

    Read straight from storage rather than through a retrieval service: the
    claim under test is that the symbols were *stored*, and going through a
    query path would let a retrieval filter hide a missing row.
    """
    snapshot = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert snapshot is not None, "indexing produced no active snapshot"
    rows = harness.connection.execute(
        "SELECT qualified_name, kind FROM symbols WHERE snapshot_id = ?",
        (snapshot.snapshot_id,),
    ).fetchall()
    return {row[0]: SymbolKind(row[1]) for row in rows}


def test_a_java_repository_indexes_into_symbols(java_harness: JavaHarness) -> None:
    java_harness.services.indexing.index(java_harness.repository_id)

    symbols = _symbols(java_harness)
    assert "OrderService" in symbols
    assert "OrderService.capture" in symbols
    assert "PaymentService.charge" in symbols
    assert symbols["OrderService"] is SymbolKind.CLASS
    assert symbols["OrderService.capture"] is SymbolKind.METHOD


def test_java_files_are_parsed_rather_than_skipped(java_harness: JavaHarness) -> None:
    """A file classified but unparsed yields no symbols and no warning."""
    result = java_harness.services.indexing.index(java_harness.repository_id)

    assert result.reuse.files_reparsed >= 2
