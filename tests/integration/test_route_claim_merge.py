"""Why ADR-0055's per-edge claim merge cannot fire, measured rather than assumed.

The Deferred Register carries this as a stated limit: the merge -- which folds a
route's two citations into **one** claim -- is not exercised by any fixture, and
deleting it leaves every test green. Its reopen trigger reads *"someone adds a
fixture whose route literal sits alone on its line"*.

**That trigger is unsatisfiable, and this module is the evidence.** Two shapes
were built and indexed:

* **Inline** -- ``const response = await fetch(`/orders/${id}`);`` -- yields
  ``loadOrder ROUTES_TO get_order`` at frontend.ts:2. But the ``CALLS fetch``
  edge cites *the same line*, comes first, and wins region deduplication, so the
  route's near-side citation is dropped and the edge survives with **one**
  citation: the handler definition. One citation, so nothing to merge.
* **Separated** -- the literal bound to its own line, then passed to ``fetch``
  -- yields **no route edge at all.** The derivation attributes a route to the
  call the literal sits in; take the literal out of the call and there is no
  route to attribute.

So the near side of a `ROUTES_TO` edge is *always* the line of a call that also
emits a `CALLS` edge, and moving it off that line destroys the edge. **The merge
is unreachable by construction, not for want of a fixture.**

These tests pin the behaviour that makes it so. If deduplication order ever
changes and the route's near side survives, the first test fails and the merge
becomes reachable -- at which point the register row can be closed properly and
the assertion inverted, on ADR-0045's precedent of inverting a pin rather than
deleting it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import QueryResponse, RelationKind
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import RelationStore, SymbolStore

BACKEND_PY = (
    'def get_order(order_id: str) -> dict[str, str]:\n'
    '    return {"id": order_id, "status": "ready"}\n'
)
# The literal inside the call: the only shape that yields a route edge.
INLINE_TS = (
    "export async function loadOrder(id: string) {\n"
    "  const response = await fetch(`/orders/${id}`);\n"
    "  return response.json();\n"
    "}\n"
)
# The literal on its own line -- the shape the register asks for.
SEPARATED_TS = (
    "export async function loadOrder(id: string) {\n"
    "  const ordersPath = `/orders/${id}`;\n"
    "  const response = await fetch(ordersPath);\n"
    "  return response.json();\n"
    "}\n"
)


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    snapshot_id: str


def _harness(tmp_path: Path, frontend: str, name: str) -> Iterator[Harness]:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "backend.py").write_text(BACKEND_PY, encoding="utf-8")
    (root / "frontend.ts").write_text(frontend, encoding="utf-8")

    with connect(tmp_path / f"{name}.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        result = services.indexing.index(repository.repository_id)
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            snapshot_id=result.snapshot.snapshot_id,
        )


@pytest.fixture()
def inline(tmp_path: Path) -> Iterator[Harness]:
    yield from _harness(tmp_path, INLINE_TS, "inline")


@pytest.fixture()
def separated(tmp_path: Path) -> Iterator[Harness]:
    yield from _harness(tmp_path, SEPARATED_TS, "separated")


def _trace(harness: Harness) -> QueryResponse:
    return harness.services.graph.trace(
        GraphQueryRequest(
            repository_id=harness.repository_id,
            symbol="loadOrder",
            request_id="route-merge",
        )
    )


def _route_edges(harness: Harness) -> list[str]:
    symbols = {
        symbol.symbol_id: symbol.qualified_name
        for symbol in SymbolStore(harness.connection).list_for_snapshot(
            harness.snapshot_id
        )
    }
    return [
        f"{symbols.get(edge.source_symbol_id, '?')} -> "
        # An unresolved edge has no target id, only the hint it was derived
        # from -- so the id is optional and reading it blindly is a type error.
        f"{symbols.get(edge.target_symbol_id or '') or edge.target_hint}"
        for edge in RelationStore(harness.connection).list_for_snapshot(
            harness.snapshot_id
        )
        if edge.kind is RelationKind.ROUTES_TO
    ]


def test_a_route_edge_needs_its_literal_inside_the_call(
    inline: Harness, separated: Harness
) -> None:
    """The register's proposed fixture shape produces no route to merge.

    This is the finding: separating the literal from the call does not merely
    move a citation, it removes the edge. A route is derived from the path
    literal in the call it is passed to.
    """
    assert _route_edges(inline) == ["loadOrder -> get_order"]
    assert _route_edges(separated) == [], (
        "the separated shape now yields a route edge; the register row's "
        "trigger has become satisfiable and the merge may be reachable"
    )


def test_the_routes_claim_carries_exactly_one_citation(inline: Harness) -> None:
    """The near side is deduplicated by the call that carries it.

    `ROUTES_TO` contributes two candidates -- the literal's line and the
    handler's definition -- but the literal's line is also where the `CALLS
    fetch` edge cites, and that edge comes first. One region is one citation, so
    the route keeps only its destination.

    **One citation means the merge has nothing to merge**, which is precisely
    why deleting it leaves every test green.
    """
    response = _trace(inline)
    routes = [
        claim for claim in response.answer.claims if "routes to" in claim.text
    ]
    assert len(routes) == 1
    assert len(routes[0].evidence_ids) == 1, (
        "the route claim now carries more than one citation, so ADR-0055's "
        "merge is reachable and this module's premise has changed"
    )


def test_the_route_cites_the_handler_rather_than_its_own_literal(
    inline: Harness,
) -> None:
    """What survives is the far side, and ADR-0055 is why that is right.

    A route's literal sits in the caller's file, in another language, and names
    a handler it never imports, so the near side alone cannot show what the flow
    reaches. Deduplication happens to drop the near side here; the carve-out is
    what guarantees the *far* side is present at all.
    """
    response = _trace(inline)
    (route,) = [c for c in response.answer.claims if "routes to" in c.text]
    cited = {
        item.evidence_id: item.file_path for item in response.evidence
    }
    assert cited[route.evidence_ids[0]].endswith("backend.py")
