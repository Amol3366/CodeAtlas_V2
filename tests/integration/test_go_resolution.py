"""Go indexing and resolution, end to end (ADR-0065).

Go is the language `owner_hint` exists for. These tests prove the receiver
reaches storage as a qualified name, and pin exactly how far resolution gets.
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

ORDERS = """package orders

import (
\t"myapp/internal/payments"
)

type OrderService struct {
\tpay *payments.Service
}

func (s *OrderService) Capture(orderID string) error {
\treturn s.pay.Charge(orderID)
}
"""

PAYMENTS = """package payments

type Service struct{}

func (s *Service) Charge(orderID string) error {
\treturn nil
}
"""


@dataclass
class GoHarness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str


@pytest.fixture()
def go_harness(tmp_path: Path) -> Iterator[GoHarness]:
    root = tmp_path / "go_app"
    (root / "internal" / "orders").mkdir(parents=True)
    (root / "internal" / "payments").mkdir(parents=True)
    (root / "internal" / "orders" / "service.go").write_text(ORDERS, encoding="utf-8")
    (root / "internal" / "payments" / "service.go").write_text(
        PAYMENTS, encoding="utf-8"
    )
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        yield GoHarness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
        )


def _rows(harness: GoHarness, table: str, columns: str) -> list[tuple[Any, ...]]:
    snapshot = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert snapshot is not None
    return list(
        harness.connection.execute(
            f"SELECT {columns} FROM {table} WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        )
    )


def test_a_go_method_is_qualified_by_its_receiver(go_harness: GoHarness) -> None:
    names = {row[0] for row in _rows(go_harness, "symbols", "qualified_name")}

    assert "OrderService.Capture" in names
    assert "Service.Charge" in names


def test_go_module_path_is_the_package_directory(go_harness: GoHarness) -> None:
    rows = _rows(go_harness, "symbols", "qualified_name, module_path")
    modules = {row[0]: row[1] for row in rows}

    assert modules["OrderService.Capture"] == "internal.orders"
    assert modules["Service.Charge"] == "internal.payments"


def test_a_cross_package_go_call_resolves(go_harness: GoHarness) -> None:
    calls = [
        row
        for row in _rows(go_harness, "relations", "kind, target_hint, resolution")
        if row[0] == "CALLS" and row[1] == "Charge"
    ]

    assert calls, "the call to Charge was not recorded"
    assert any(row[2] == "resolved" for row in calls)


def test_a_go_builtin_is_not_invented_as_a_local_symbol(
    go_harness: GoHarness,
) -> None:
    """`string` and `error` are builtins, not repository symbols."""
    builtins = [
        row
        for row in _rows(go_harness, "relations", "kind, target_hint, resolution")
        if row[1] in {"string", "error"}
    ]

    assert builtins
    assert all(row[2] != "resolved" for row in builtins)


GO_IMPORT_FINDING = (
    "ADR-0065 Go slice, measured 2026-08-19. A Go import path carries the module "
    "prefix declared in go.mod -- `myapp/internal/payments` -- while the indexed "
    "module path is the repository-relative directory, `internal.payments`. "
    "`_resolve_module` matches a specifier against tails of MODULE PATHS, not "
    "tails of the SPECIFIER, so the longer specifier never matches and the "
    "import is classified `external`. Resolving it needs a matching policy: how "
    "many leading segments may be discarded before a match counts. That is a "
    "product judgement with an asymmetric cost -- trimming to a single segment "
    "would make a third-party `github.com/foo/payments` resolve onto a local "
    "`payments` package, which invents a relationship and violates section 4.1 -- "
    "so it is recorded for a decision rather than chosen here."
)


@pytest.mark.xfail(strict=True, reason=GO_IMPORT_FINDING)
def test_a_go_import_resolves_across_packages(go_harness: GoHarness) -> None:
    imports = [
        row
        for row in _rows(go_harness, "relations", "kind, target_hint, resolution")
        if row[0] == "IMPORTS"
    ]

    assert imports, "no IMPORTS relations stored at all"
    assert any(row[2] == "resolved" for row in imports)
