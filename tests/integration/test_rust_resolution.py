"""Rust indexing and resolution, end to end (ADR-0065).

Rust is the first query-backed language whose *imports* resolve. The reason is
worth stating: `crate` is a Rust keyword, so stripping it from a `use` path is
safe, where Go's equivalent prefix comes from `go.mod` and cannot be known from
one file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

ORDERS = """use crate::payments::Service;

pub struct OrderService {
    pay: Service,
}

impl OrderService {
    pub fn capture(&self, order_id: &str) -> u32 {
        self.pay.charge(order_id);
        1
    }
}
"""

PAYMENTS = """pub struct Service {}

impl Service {
    pub fn charge(&self, order_id: &str) {}
}
"""


@dataclass
class RustHarness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str


@pytest.fixture()
def rust_harness(tmp_path: Path) -> Iterator[RustHarness]:
    root = tmp_path / "rust_app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "orders.rs").write_text(ORDERS, encoding="utf-8")
    (root / "src" / "payments.rs").write_text(PAYMENTS, encoding="utf-8")
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        yield RustHarness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
        )


def _rows(harness: RustHarness, table: str, columns: str) -> list[tuple[Any, ...]]:
    snapshot = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert snapshot is not None
    return list(
        harness.connection.execute(
            f"SELECT {columns} FROM {table} WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        )
    )


def test_a_rust_method_is_qualified_by_its_impl_type(rust_harness: RustHarness) -> None:
    names = {row[0] for row in _rows(rust_harness, "symbols", "qualified_name")}

    assert "OrderService.capture" in names
    assert "Service.charge" in names


def test_a_rust_method_is_stored_once(rust_harness: RustHarness) -> None:
    """tags.scm matches a method twice; the engine keeps the specific kind."""
    rows = _rows(rust_harness, "symbols", "qualified_name, kind")
    capture = [row for row in rows if row[0] == "OrderService.capture"]

    assert len(capture) == 1
    assert capture[0][1] == "METHOD"


def test_a_cross_module_rust_call_resolves(rust_harness: RustHarness) -> None:
    calls = [
        row
        for row in _rows(rust_harness, "relations", "kind, target_hint, resolution")
        if row[0] == "CALLS" and row[1] == "charge"
    ]

    assert calls
    assert any(row[2] == "resolved" for row in calls)


def test_a_rust_use_import_resolves_because_crate_is_a_keyword(
    rust_harness: RustHarness,
) -> None:
    """The contrast with Go, which is the point.

    `use crate::payments::Service` can be stripped to `payments::Service`
    because `crate` is defined by the language. Go's `myapp/internal/payments`
    carries a prefix from `go.mod`, which one file cannot know, so its import
    stays `external`.
    """
    imports = [
        row
        for row in _rows(rust_harness, "relations", "kind, target_hint, resolution")
        if row[0] == "IMPORTS"
    ]

    assert imports, "no IMPORTS relations stored at all"
    assert any(row[1] == "Service" and row[2] == "resolved" for row in imports)
