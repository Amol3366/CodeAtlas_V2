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


# --- Fixture-mediated TESTS derivation -----------------------------------------


def _tests_edges(
    harness: Harness,
    snapshot_id: str,
    relations: tuple[RelationRecord, ...],
    *,
    source_hint: str,
    target_hint: str,
) -> tuple[RelationRecord, ...]:
    """`TESTS` edges from the named source to the named target.

    Filtering by target hint alone is not enough: a fixture function that
    itself imports and calls the target produces its own strict `TESTS` edge
    (fixtures live in `conftest.py`, which is `TEST_CODE` too), and that edge
    must not be mistaken for the one under test.
    """
    source_id = _symbol_id(harness, snapshot_id, source_hint)
    return tuple(
        item
        for item in relations
        if item.kind is RelationKind.TESTS
        and item.target_hint == target_hint
        and item.source_symbol_id == source_id
    )


def _build_repo(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


# Never closed: these are tmp_path-scoped sqlite files that vanish with the test
# directory, and closing early is the bug `_index` works around (see below).
_OPEN_CONNECTION_MANAGERS: list[object] = []


def _index(
    tmp_path: Path, root: Path
) -> tuple[Harness, str, tuple[RelationRecord, ...]]:
    """Register and index a fresh repository, connection kept open for the caller.

    The connection is deliberately never closed here: closing it would make the
    harness unusable for a second ``index`` call or a later query, exactly the
    trap the fixture-based ``harness`` avoids via `Iterator` + `yield`.
    """
    # The context manager object itself must be kept alive: if it is garbage
    # collected, its generator's `finally` runs and closes the connection out
    # from under this function, well before the caller is done with it.
    manager = connect(tmp_path / "db.sqlite")
    connection = manager.__enter__()
    _OPEN_CONNECTION_MANAGERS.append(manager)
    apply_migrations(connection)
    services = build_services(connection)
    repository = services.registration.register(
        RegisterRepositoryRequest(path=str(root))
    )
    harness = Harness(
        services=services,
        connection=connection,
        repository_id=repository.repository_id,
        root=root,
    )
    result = harness.services.indexing.index(harness.repository_id)
    snapshot_id = result.snapshot.snapshot_id
    relations = _relations(harness, snapshot_id)
    return harness, snapshot_id, relations


def test_a_fixture_mediated_test_produces_a_weak_edge(tmp_path: Path) -> None:
    """conftest.py builds the object; the test never imports or calls it."""
    root = _build_repo(
        tmp_path,
        "fixture_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "conftest.py": (
                "import pytest\n"
                "from orders import Order\n"
                "\n"
                "@pytest.fixture\n"
                "def order():\n"
                "    return Order()\n"
            ),
            "test_orders.py": (
                "def test_total(order):\n"
                "    assert order is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness, snapshot_id, relations, source_hint="test_total", target_hint="Order"
    )
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.LOW_CONFIDENCE_HEURISTIC


def test_a_strict_edge_is_not_replaced_by_a_fixture_edge(tmp_path: Path) -> None:
    """The test both imports+calls the target AND consumes a fixture reaching it."""
    root = _build_repo(
        tmp_path,
        "strict_and_fixture_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "conftest.py": (
                "import pytest\n"
                "from orders import Order\n"
                "\n"
                "@pytest.fixture\n"
                "def order():\n"
                "    return Order()\n"
            ),
            "test_orders.py": (
                "from orders import Order\n"
                "\n"
                "def test_total(order):\n"
                "    assert Order() is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness, snapshot_id, relations, source_hint="test_total", target_hint="Order"
    )
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC


def test_a_fixture_in_an_ancestor_conftest_resolves(tmp_path: Path) -> None:
    root = _build_repo(
        tmp_path,
        "ancestor_conftest_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "conftest.py": (
                "import pytest\n"
                "from orders import Order\n"
                "\n"
                "@pytest.fixture\n"
                "def order():\n"
                "    return Order()\n"
            ),
            "tests/unit/test_orders.py": (
                "def test_total(order):\n"
                "    assert order is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    assert _tests_edges(
        harness,
        snapshot_id,
        relations,
        source_hint="test_total",
        target_hint="Order",
    )


def test_the_nearest_conftest_wins(tmp_path: Path) -> None:
    """Two conftest.py files define `store`; the deeper one must be chosen."""
    root = _build_repo(
        tmp_path,
        "shadowed_conftest_repo",
        {
            "orders.py": (
                "class Distant:\n    pass\n\n\nclass Nearest:\n    pass\n"
            ),
            "conftest.py": (
                "import pytest\n"
                "from orders import Distant\n"
                "\n"
                "@pytest.fixture\n"
                "def store():\n"
                "    return Distant()\n"
            ),
            "tests/unit/conftest.py": (
                "import pytest\n"
                "from orders import Nearest\n"
                "\n"
                "@pytest.fixture\n"
                "def store():\n"
                "    return Nearest()\n"
            ),
            "tests/unit/test_orders.py": (
                "def test_total(store):\n"
                "    assert store is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness,
        snapshot_id,
        relations,
        source_hint="test_total",
        target_hint="Nearest",
    )
    assert len(edges) == 1
    distant_edges = _tests_edges(
        harness,
        snapshot_id,
        relations,
        source_hint="test_total",
        target_hint="Distant",
    )
    assert distant_edges == ()


def test_an_unresolved_parameter_produces_no_edge_and_no_error(
    tmp_path: Path,
) -> None:
    """A parameter naming no fixture in scope is ordinary — it may come from a
    plugin. It is not a defect to report."""
    root = _build_repo(
        tmp_path,
        "unknown_parameter_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "test_orders.py": (
                "def test_total(mystery_plugin_fixture):\n"
                "    assert mystery_plugin_fixture is not None\n"
            ),
        },
    )
    _harness, _snapshot_id, relations = _index(tmp_path, root)

    tests_from_source = [
        item
        for item in relations
        if item.kind is RelationKind.TESTS
    ]
    assert tests_from_source == []


# --- Helper-mediated TESTS derivation ------------------------------------------


def test_a_helper_mediated_test_produces_a_weak_edge(tmp_path: Path) -> None:
    """test_total -> _build (same test file) -> orders.Order."""
    root = _build_repo(
        tmp_path,
        "helper_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "test_orders.py": (
                "from orders import Order\n"
                "\n"
                "def _build():\n"
                "    return Order()\n"
                "\n"
                "def test_total():\n"
                "    assert _build() is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness, snapshot_id, relations, source_hint="test_total", target_hint="Order"
    )
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.LOW_CONFIDENCE_HEURISTIC


def test_a_two_hop_helper_chain_produces_nothing(tmp_path: Path) -> None:
    """test_total -> _outer -> _inner -> orders.Order.

    Depth is fixed at one intermediate hop; two hops through shared utilities
    would reach most of a codebase and make the signal worthless.
    """
    root = _build_repo(
        tmp_path,
        "two_hop_helper_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "test_orders.py": (
                "from orders import Order\n"
                "\n"
                "def _inner():\n"
                "    return Order()\n"
                "\n"
                "def _outer():\n"
                "    return _inner()\n"
                "\n"
                "def test_total():\n"
                "    assert _outer() is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    assert (
        _tests_edges(
            harness,
            snapshot_id,
            relations,
            source_hint="test_total",
            target_hint="Order",
        )
        == ()
    )


def test_a_helper_outside_a_test_file_is_not_a_helper(tmp_path: Path) -> None:
    """The intermediate must itself live in test code, or this is an ordinary
    two-hop call chain through production code."""
    root = _build_repo(
        tmp_path,
        "production_intermediate_repo",
        {
            "orders.py": (
                "class Order:\n    pass\n\n\ndef build():\n    return Order()\n"
            ),
            "test_orders.py": (
                "from orders import build\n"
                "\n"
                "def test_total():\n"
                "    assert build() is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    assert (
        _tests_edges(
            harness,
            snapshot_id,
            relations,
            source_hint="test_total",
            target_hint="Order",
        )
        == ()
    )


def test_a_strict_edge_is_not_replaced_by_a_helper_edge(tmp_path: Path) -> None:
    """The test both imports+calls the target AND reaches it via a helper."""
    root = _build_repo(
        tmp_path,
        "strict_and_helper_repo",
        {
            "orders.py": "class Order:\n    pass\n",
            "test_orders.py": (
                "from orders import Order\n"
                "\n"
                "def _build():\n"
                "    return Order()\n"
                "\n"
                "def test_total():\n"
                "    _build()\n"
                "    assert Order() is not None\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness, snapshot_id, relations, source_hint="test_total", target_hint="Order"
    )
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC


# --- Method-level TESTS derivation ---------------------------------------------


_METHOD_REPO = {
    "service.py": (
        "class PaymentService:\n"
        "    def capture(self, key):\n"
        "        return key\n"
        "\n"
        "    def refund(self, key):\n"
        "        return key\n"
    ),
    "test_service.py": (
        "from service import PaymentService\n"
        "\n"
        "def test_capture():\n"
        "    service = PaymentService()\n"
        "    assert service.capture('k') == 'k'\n"
    ),
}


def test_a_resolved_call_to_a_method_produces_a_tests_edge(tmp_path: Path) -> None:
    """A method is never imported, so import-and-call could never reach one.

    The rule is satisfied at the right granularity: the *class* is imported and
    the *method* is called, and the resolver has already resolved that call to
    the exact symbol. Before this, no method anywhere could carry a `TESTS`
    edge.
    """
    root = _build_repo(tmp_path, "method_repo", dict(_METHOD_REPO))
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness,
        snapshot_id,
        relations,
        source_hint="test_capture",
        target_hint="capture",
    )
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.STATIC_RESOLVED
    assert edges[0].resolution is ResolutionState.RESOLVED


def test_an_uncalled_method_of_an_imported_class_gets_no_edge(
    tmp_path: Path,
) -> None:
    """Importing the class must not vouch for every method it owns.

    `refund` is never called. Emitting an edge for it would turn one import
    into blanket coverage of the whole class, which is the promotion this
    product exists to refuse.
    """
    root = _build_repo(tmp_path, "uncalled_repo", dict(_METHOD_REPO))
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness,
        snapshot_id,
        relations,
        source_hint="test_capture",
        target_hint="refund",
    )
    assert edges == ()


def test_a_locally_defined_test_double_is_not_reported_as_tested(
    tmp_path: Path,
) -> None:
    """The owner must be imported: a fake defined in the test file is not."""
    root = _build_repo(
        tmp_path,
        "double_repo",
        {
            "test_double.py": (
                "class FakeStore:\n"
                "    def claim(self, key):\n"
                "        return key\n"
                "\n"
                "def test_it():\n"
                "    assert FakeStore().claim('k') == 'k'\n"
            ),
        },
    )
    harness, snapshot_id, relations = _index(tmp_path, root)

    edges = _tests_edges(
        harness, snapshot_id, relations, source_hint="test_it", target_hint="claim"
    )
    assert edges == ()
