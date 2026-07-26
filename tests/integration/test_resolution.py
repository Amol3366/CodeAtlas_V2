"""Snapshot-wide resolution, proven against a real index rather than a stub.

The two claims under test are in tension by design: an unchanged file's
references are reused, *and* every target is re-resolved from scratch. A design
that only did the first would be fast and wrong; one that only did the second
would be correct and wasteful. Both are asserted by counter, not by inspection.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import Derivation, RelationKind
from codeatlas.domain.relations import RelationRecord, ResolutionState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import RelationStore, SymbolStore

ORDERS_TS = (
    "export interface Order {\n"
    "  id: string;\n"
    "}\n"
    "\n"
    "export function total(order: Order): number {\n"
    "  return order.id.length;\n"
    "}\n"
)
CLIENT_JS = (
    'import { total } from "./orders";\n'
    "\n"
    "export function render(order) {\n"
    "  return `Total: ${total(order)}`;\n"
    "}\n"
)
SERVICE_PY = (
    "from .idempotency import IdempotencyStore\n"
    "\n"
    "class PaymentService:\n"
    "    def __init__(self, store: IdempotencyStore) -> None:\n"
    "        self.store = store\n"
    "\n"
    "    def capture(self, key: str) -> str:\n"
    "        return self.store.claim(key)\n"
)
IDEMPOTENCY_PY = (
    "class IdempotencyStore:\n"
    "    def claim(self, key: str) -> str:\n"
    "        return key\n"
)


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    root: Path


@pytest.fixture()
def polyglot_repo(tmp_path: Path) -> Path:
    root = tmp_path / "polyglot"
    (root / "src" / "payments").mkdir(parents=True)
    (root / "src" / "orders.ts").write_text(ORDERS_TS, encoding="utf-8")
    (root / "src" / "client.js").write_text(CLIENT_JS, encoding="utf-8")
    (root / "src" / "payments" / "service.py").write_text(SERVICE_PY, encoding="utf-8")
    (root / "src" / "payments" / "idempotency.py").write_text(
        IDEMPOTENCY_PY, encoding="utf-8"
    )
    return root


@pytest.fixture()
def harness(tmp_path: Path, polyglot_repo: Path) -> Iterator[Harness]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(polyglot_repo))
        )
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=polyglot_repo,
        )


def _relations(harness: Harness, snapshot_id: str) -> tuple[RelationRecord, ...]:
    return RelationStore(harness.connection).list_for_snapshot(snapshot_id)


def _symbol_id(harness: Harness, snapshot_id: str, qualified_name: str) -> str:
    for symbol in SymbolStore(harness.connection).list_for_snapshot(snapshot_id):
        if symbol.qualified_name == qualified_name:
            return symbol.symbol_id
    raise AssertionError(f"no symbol named {qualified_name}")


def _find(
    relations: tuple[RelationRecord, ...], kind: RelationKind, hint: str
) -> RelationRecord:
    matches = [
        item for item in relations if item.kind is kind and item.target_hint == hint
    ]
    assert matches, f"no {kind.value} relation for {hint}"
    return matches[0]


# --- Step 1: cross-file and cross-language resolution -------------------------


def test_a_cross_file_call_resolves_to_the_real_target_symbol(
    harness: Harness,
) -> None:
    """`render` calls `total` across client.js and orders.ts."""
    result = harness.services.indexing.index(harness.repository_id)
    snapshot_id = result.snapshot.snapshot_id

    call = _find(_relations(harness, snapshot_id), RelationKind.CALLS, "total")

    assert call.resolution is ResolutionState.RESOLVED
    assert call.target_symbol_id == _symbol_id(harness, snapshot_id, "total")
    assert call.derivation is Derivation.STATIC_RESOLVED


def test_a_relative_import_resolves_across_files(harness: Harness) -> None:
    result = harness.services.indexing.index(harness.repository_id)
    snapshot_id = result.snapshot.snapshot_id

    imported = _find(
        _relations(harness, snapshot_id), RelationKind.IMPORTS, "IdempotencyStore"
    )

    assert imported.resolution is ResolutionState.RESOLVED
    assert imported.target_symbol_id == _symbol_id(
        harness, snapshot_id, "IdempotencyStore"
    )


def test_a_python_cross_file_call_resolves(harness: Harness) -> None:
    result = harness.services.indexing.index(harness.repository_id)
    snapshot_id = result.snapshot.snapshot_id

    call = _find(_relations(harness, snapshot_id), RelationKind.CALLS, "claim")

    assert call.resolution is ResolutionState.RESOLVED
    assert call.target_symbol_id == _symbol_id(
        harness, snapshot_id, "IdempotencyStore.claim"
    )


def test_a_bare_specifier_is_external_and_reads_no_package_directory(
    harness: Harness,
) -> None:
    (harness.root / "src" / "vendor.js").write_text(
        'import React from "react";\nexport function view() { return React; }\n',
        encoding="utf-8",
    )
    result = harness.services.indexing.index(harness.repository_id)

    imported = _find(
        _relations(harness, result.snapshot.snapshot_id),
        RelationKind.IMPORTS,
        "default",
    )

    assert imported.resolution is ResolutionState.EXTERNAL
    assert imported.target_symbol_id is None
    # The statement is a fact even though nothing in the repository answers it.
    assert imported.derivation is Derivation.DETERMINISTIC


# --- Step 2: staleness, gate condition 7 --------------------------------------


def test_a_removed_target_leaves_an_unresolved_edge_not_a_dangling_one(
    harness: Harness,
) -> None:
    harness.services.indexing.index(harness.repository_id)

    (harness.root / "src" / "orders.ts").write_text(
        "export interface Order {\n  id: string;\n}\n", encoding="utf-8"
    )
    result = harness.services.indexing.index(harness.repository_id)
    snapshot_id = result.snapshot.snapshot_id

    call = _find(_relations(harness, snapshot_id), RelationKind.CALLS, "total")
    assert call.resolution is not ResolutionState.RESOLVED
    assert call.target_symbol_id is None


def test_no_relation_in_an_active_snapshot_points_outside_it(
    harness: Harness,
) -> None:
    """Gate condition 7, asserted against the database that serves queries."""
    harness.services.indexing.index(harness.repository_id)
    (harness.root / "src" / "orders.ts").write_text(
        "export interface Order {\n  id: string;\n}\n", encoding="utf-8"
    )
    result = harness.services.indexing.index(harness.repository_id)
    snapshot_id = result.snapshot.snapshot_id

    known = {
        symbol.symbol_id
        for symbol in SymbolStore(harness.connection).list_for_snapshot(snapshot_id)
    }
    for relation in _relations(harness, snapshot_id):
        if relation.target_symbol_id is not None:
            assert relation.target_symbol_id in known
        assert relation.source_symbol_id in known

    assert RelationStore(harness.connection).dangling_endpoints(snapshot_id) == ()


# --- Step 3: reuse and full re-resolution in the same run ---------------------


def test_reuse_and_full_reresolution_hold_together(harness: Harness) -> None:
    """Gate condition 6: references reused, targets recomputed, both counted."""
    first = harness.services.indexing.index(harness.repository_id)
    total_references = first.reuse.references_extracted

    service = harness.root / "src" / "payments" / "service.py"
    service.write_text(
        service.read_text(encoding="utf-8").replace(
            "return self.store.claim(key)", "return self.store.claim(key.strip())"
        ),
        encoding="utf-8",
    )
    second = harness.services.indexing.index(harness.repository_id)

    # References from untouched files were carried, not re-extracted.
    assert second.reuse.references_reused > 0
    # Only the edited file was re-extracted.
    assert second.reuse.references_extracted < total_references
    # Yet resolution covered the whole snapshot, every run.
    assert second.reuse.relations_resolved == (
        second.reuse.references_reused + second.reuse.references_extracted
    )


def test_a_carried_reference_keeps_its_module_hint(harness: Harness) -> None:
    """An import carried across a rebuild must still know what it imported."""
    harness.services.indexing.index(harness.repository_id)
    service = harness.root / "src" / "payments" / "service.py"
    service.write_text(
        service.read_text(encoding="utf-8") + "\nVALUE = 1\n", encoding="utf-8"
    )
    result = harness.services.indexing.index(harness.repository_id)

    imported = _find(
        _relations(harness, result.snapshot.snapshot_id),
        RelationKind.IMPORTS,
        "total",
    )

    assert imported.module_hint == "./orders"
    assert imported.resolution is ResolutionState.RESOLVED


def test_resolution_is_deterministic_across_runs(harness: Harness) -> None:
    first = harness.services.indexing.index(harness.repository_id)
    relations = _relations(harness, first.snapshot.snapshot_id)

    repeated = harness.services.indexing.index(harness.repository_id)

    assert repeated.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert _relations(harness, repeated.snapshot.snapshot_id) == relations


# --- Ambiguity ----------------------------------------------------------------


def test_an_ambiguous_name_becomes_may_call_never_calls(harness: Harness) -> None:
    """Two symbols share a name, so the call site cannot mean exactly one."""
    (harness.root / "src" / "alpha.py").write_text(
        "class Alpha:\n    def handle(self):\n        return 1\n", encoding="utf-8"
    )
    (harness.root / "src" / "beta.py").write_text(
        "class Beta:\n    def handle(self):\n        return 2\n", encoding="utf-8"
    )
    (harness.root / "src" / "caller.py").write_text(
        "def run(thing):\n    return thing.handle()\n", encoding="utf-8"
    )
    result = harness.services.indexing.index(harness.repository_id)

    relations = _relations(harness, result.snapshot.snapshot_id)
    handle = [item for item in relations if item.target_hint == "handle"]

    assert handle, "expected a relation for the ambiguous call"
    assert all(item.kind is not RelationKind.CALLS for item in handle)
    assert any(item.kind is RelationKind.MAY_CALL for item in handle)
    ambiguous = next(item for item in handle if item.kind is RelationKind.MAY_CALL)
    assert ambiguous.resolution is ResolutionState.AMBIGUOUS
    assert ambiguous.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
    assert ambiguous.candidate_count > 1
    assert ambiguous.target_symbol_id is None


def test_the_snapshot_records_its_resolver_version(harness: Harness) -> None:
    result = harness.services.indexing.index(harness.repository_id)

    assert result.snapshot.resolver_version != ""
