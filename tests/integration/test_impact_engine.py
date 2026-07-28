"""Impact expansion over a graph a real index produced.

`test_impact.py` and `test_impact_cases.py` build graphs by hand, which is what
makes the orientation rules readable. This file checks the same engine against
edges that came out of the parser, the resolver, and SQLite — so a rule that
only works on hand-written relations fails here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.analysis.impact import GraphSide, ImpactBounds, analyze_impact
from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import ChangeKind, RelationKind, SymbolKind
from codeatlas.domain.change import SymbolChange
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import RelationStore, SymbolStore

BACKEND_PY = (
    'def get_order(order_id: str) -> dict[str, str]:\n'
    '    return {"id": order_id, "status": "ready"}\n'
    "\n"
    "def health() -> str:\n"
    '    return "ok"\n'
)
FRONTEND_TS = (
    "export async function loadOrder(id: string) {\n"
    "  const response = await fetch(`/orders/${id}`);\n"
    "  return response.json();\n"
    "}\n"
    "\n"
    'export const healthPath = "/health";\n'
)
FLOW_MD = (
    "# Order flow\n"
    "\n"
    "The frontend requests `/orders/{id}`.\n"
    "\n"
    "The backend returns the order status.\n"
)


@dataclass
class Indexed:
    connection: sqlite3.Connection
    snapshot_id: str


@pytest.fixture()
def indexed(tmp_path: Path) -> Iterator[Indexed]:
    root = tmp_path / "mixed"
    for relative, content in {
        "backend.py": BACKEND_PY,
        "frontend.ts": FRONTEND_TS,
        "docs/flow.md": FLOW_MD,
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        result = services.indexing.index(repository.repository_id)
        yield Indexed(connection=connection, snapshot_id=result.snapshot.snapshot_id)


def _side(indexed: Indexed) -> GraphSide:
    symbols = SymbolStore(indexed.connection).list_for_snapshot(indexed.snapshot_id)
    relations = RelationStore(indexed.connection).list_for_snapshot(
        indexed.snapshot_id
    )
    return GraphSide(
        symbols={symbol.symbol_id: symbol for symbol in symbols},
        relations=relations,
    )


def _change(
    name: str,
    kind: ChangeKind = ChangeKind.MODIFIED,
    symbol_kind: SymbolKind = SymbolKind.FUNCTION,
) -> SymbolChange:
    return SymbolChange(
        qualified_name=name,
        symbol_kind=symbol_kind,
        change_kind=kind,
        file_path="backend.py",
    )


def test_a_backend_change_reaches_its_frontend_caller_and_its_document(
    indexed: Indexed,
) -> None:
    """c015 over real edges: the route and the document both lead back here."""
    side = _side(indexed)

    result = analyze_impact([_change("get_order")], base=side, target=side)

    assert set(result.paths) == {
        ("get_order", "loadOrder"),
        ("get_order", "Order flow"),
    }


def test_a_frontend_change_reaches_the_handler_it_addresses(
    indexed: Indexed,
) -> None:
    side = _side(indexed)

    result = analyze_impact([_change("loadOrder")], base=side, target=side)

    assert ("loadOrder", "get_order") in result.paths


def test_a_constant_change_reaches_the_handler_its_path_names(
    indexed: Indexed,
) -> None:
    """c018: the route-derived `REFERENCES` edge travels outward too."""
    side = _side(indexed)

    result = analyze_impact(
        [_change("healthPath", symbol_kind=SymbolKind.CONSTANT)],
        base=side,
        target=side,
    )

    assert ("healthPath", "health") in result.paths


def test_every_reported_edge_carries_the_derivation_it_was_resolved_with(
    indexed: Indexed,
) -> None:
    """A heuristic edge must not read as a resolved one further downstream."""
    side = _side(indexed)

    result = analyze_impact([_change("get_order")], base=side, target=side)

    assert result.edges
    for edge in result.edges:
        stored = next(
            item
            for item in side.relations
            if item.kind is edge.kind and item.derivation is edge.derivation
        )
        assert edge.confidence == stored.confidence


def test_a_changed_symbol_with_no_test_edge_is_reported_as_a_gap(
    indexed: Indexed,
) -> None:
    side = _side(indexed)

    result = analyze_impact([_change("get_order")], base=side, target=side)

    assert "get_order" in result.test_gaps


def test_a_deleted_symbol_reports_the_dependent_left_behind(
    indexed: Indexed,
) -> None:
    """Deleting `get_order` leaves `loadOrder` addressing a path nothing serves."""
    base = _side(indexed)
    target = GraphSide(
        symbols={
            symbol_id: record
            for symbol_id, record in base.symbols.items()
            if record.qualified_name != "get_order"
        },
        relations=tuple(
            relation
            for relation in base.relations
            if base.symbols.get(relation.target_symbol_id or "", None) is None
            or base.symbols[relation.target_symbol_id or ""].qualified_name
            != "get_order"
        ),
    )

    result = analyze_impact(
        [_change("get_order", ChangeKind.DELETED)], base=base, target=target
    )

    assert "loadOrder" in result.unresolved_dependents
    assert ("get_order", "loadOrder") in result.paths


def test_expansion_stays_within_its_bounds_on_a_real_graph(
    indexed: Indexed,
) -> None:
    side = _side(indexed)

    result = analyze_impact(
        [_change("get_order")],
        base=side,
        target=side,
        bounds=ImpactBounds(max_depth=1, max_edges=1),
    )

    assert len(result.paths) <= 1
    assert result.truncated_by


def test_no_structural_edge_is_ever_reported_as_impact(
    indexed: Indexed,
) -> None:
    """A module is not affected by a function inside it changing.

    Both `CONTAINS` and `EXPORTS` say where a symbol lives. Following either one
    walks every symbol back up to its file, and the report becomes a list of
    modules. The hand-built tables in `test_impact_cases.py` carry no `EXPORTS`
    edges, so only a real indexed graph catches this.
    """
    side = _side(indexed)
    structural = {RelationKind.CONTAINS, RelationKind.EXPORTS}

    for name in ("get_order", "health", "loadOrder"):
        result = analyze_impact([_change(name)], base=side, target=side)
        assert all(edge.kind not in structural for edge in result.edges)
