"""Does `resolution.py` generalize to a non-Python module system? (ADR-0065)

This is the checkpoint the ADR-0065 plan exists to reach. The design assumes
Java's `com.shop.orders` resolves against `com/shop/orders/` through the
`module_suffix_to_file` index ADR-0064 built, with no per-language rules. That
assumption was read from the resolver, never run.

Both outcomes are results. A failure here is the checkpoint working.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
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
        services.indexing.index(repository.repository_id)
        yield JavaHarness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
        )


def _relations(harness: JavaHarness) -> list[tuple[str, str, str, str | None]]:
    """(kind, target_hint, resolution, derivation) for the active snapshot."""
    snapshot = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert snapshot is not None
    return [
        (row[0], row[1], row[2], row[3])
        for row in harness.connection.execute(
            "SELECT kind, target_hint, resolution, derivation FROM relations"
            " WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchall()
    ]


CHECKPOINT_REASON = (
    "ADR-0065 checkpoint, measured 2026-08-19: resolution.py does NOT generalize. "
    "`_build_index` gates the module index on `record.language == \"python\"` "
    "(resolution.py:236) and derives the module from the FILE PATH via "
    "`_python_module`, so a Java package never enters `module_to_file` -- and "
    "would not match if it did, because the path yields "
    "`src.main.java.com.shop.payments` while the declared package is "
    "`com.shop.payments`. The import is therefore classified `external`. "
    "Fixing it means indexing a declared module_path for non-Python languages, "
    "which is a RESOLVER_VERSION bump and a second forced reindex -- scoped as "
    "conditional in ADR-0065 and awaiting a decision."
)


@pytest.mark.xfail(strict=True, reason=CHECKPOINT_REASON)
def test_a_java_import_resolves_across_packages(java_harness: JavaHarness) -> None:
    relations = _relations(java_harness)
    imports = [r for r in relations if r[0] == "IMPORTS"]
    assert imports, f"no IMPORTS relations stored at all; got {relations}"
    resolved = [r for r in imports if r[2] == "resolved"]
    states = [(r[1], r[2]) for r in imports]
    assert resolved, f"no Java import resolved; states={states}"


def test_a_java_call_resolves_to_the_imported_class_method(
    java_harness: JavaHarness,
) -> None:
    relations = _relations(java_harness)
    calls = [r for r in relations if r[0] == "CALLS" and r[1] == "charge"]
    assert calls, f"the call to charge was not recorded; got {relations}"
    assert any(r[2] == "resolved" for r in calls), (
        f"charge never resolved; states={[r[2] for r in calls]}"
    )


def test_a_resolved_java_edge_carries_a_defensible_derivation(
    java_harness: JavaHarness,
) -> None:
    """Spec section 6: a resolved query-backed edge is static_resolved, and an
    unresolved one is never promoted. Query captures carry no receiver context,
    so this is the ceiling rather than parity with Python.
    """
    relations = _relations(java_harness)
    resolved = [r for r in relations if r[2] == "resolved"]
    assert resolved
    for relation in resolved:
        assert relation[3] in {"static_resolved", "deterministic"}
    # `external` legitimately carries `deterministic`: the resolver concluded
    # with certainty that the target lies outside the repository. Only a
    # genuinely *unresolved* edge -- one it could not decide -- must not claim
    # the top of the ladder.
    for relation in relations:
        if relation[2] == "unresolved":
            assert relation[3] != "deterministic"
