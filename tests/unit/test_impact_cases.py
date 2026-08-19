"""The orientation rules, pinned against all 28 declared change cases.

`tests/unit/test_impact.py` proves each rule in isolation. This file proves the
rules *together* reproduce every impact-path set the Phase 0 corpus declares,
which is the claim the Phase 4 plan makes and the one that decides
`direct_impact_recall` at the gate.

Each row states the edges that exist in the relevant graph and the symbols that
changed. Nothing here reads the corpus fixtures: the point is to pin the
orientation rule per case, so the graph is stated explicitly and the expectation
is copied from `changes.json`. P4-10 runs the real engine over the real corpus;
if these two disagree, one of them is wrong and that is worth finding out.

Symbol names are the engine's qualified names. Where the corpus labels a symbol
differently — `README.Sample Service` for a section whose qualified name is
`Sample Service` — the label mapping is P4-10's job, and the divergence is
recorded in the PLAN.md handoff rather than papered over here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.analysis.impact import GraphSide, analyze_impact
from codeatlas.contracts import ChangeKind, Derivation, RelationKind, SymbolKind
from codeatlas.domain.change import SymbolChange
from codeatlas.domain.relations import (
    ROUTE_HINT,
    RelationRecord,
    ResolutionState,
)
from codeatlas.domain.symbols import SymbolRecord

CHANGES = Path("tests/evaluation/cases/changes.json")

# How the corpus labels a symbol, when that differs from its qualified name.
#
# Two conventions, both of which P4-10's `predict_changes` has to reproduce:
#
# * a `docs_config` document section carries a file-stem prefix, while
#   `mixed_app`'s sections carry none, and no uniqueness rule explains the
#   difference — it is recorded in the PLAN.md handoff as a corpus quirk;
# * a configuration key is labeled by the dotted leaf path whose value changed,
#   while being cited at its top-level block's range. P4-05 gave YAML the nested
#   dotted paths that make this derivable.
CORPUS_LABELS: dict[str, str] = {
    "Sample Service": "README.Sample Service",
    "Health": "README.Health",
    "service": "service.port",
    "scripts": "scripts.test",
}


@dataclass(frozen=True)
class Case:
    """One corpus case reduced to the graph its impact depends on."""

    case_id: str
    symbols: dict[str, SymbolKind]
    edges: tuple[tuple[str, str, RelationKind], ...]
    changes: tuple[tuple[str, ChangeKind], ...]
    # Edges whose `REFERENCES` came from a route literal rather than a type
    # reference. They travel both ways; a type reference does not.
    route_edges: frozenset[tuple[str, str]] = frozenset()
    deleted_in_target: tuple[str, ...] = ()


PY = SymbolKind.FUNCTION
METHOD = SymbolKind.METHOD
CLASS = SymbolKind.CLASS
TEST = SymbolKind.TEST
DOC = SymbolKind.DOCUMENT_SECTION
CONFIG = SymbolKind.CONFIG_KEY
CONST = SymbolKind.CONSTANT
IFACE = SymbolKind.INTERFACE

CALLS = RelationKind.CALLS
IMPORTS = RelationKind.IMPORTS
REFERENCES = RelationKind.REFERENCES
ROUTES_TO = RelationKind.ROUTES_TO
DOCUMENTS = RelationKind.DOCUMENTS
CONTAINS = RelationKind.CONTAINS
TESTS = RelationKind.TESTS

_PYTHON_APP = {
    "PaymentService": CLASS,
    "PaymentService.capture": METHOD,
    "PaymentService.__init__": METHOD,
    "IdempotencyStore": CLASS,
    "IdempotencyStore.claim": METHOD,
    "IdempotencyStore.__init__": METHOD,
    "test_capture_uses_idempotency_store": TEST,
}
_PYTHON_EDGES = (
    ("PaymentService", "PaymentService.capture", CONTAINS),
    ("PaymentService", "PaymentService.__init__", CONTAINS),
    ("IdempotencyStore", "IdempotencyStore.claim", CONTAINS),
    ("IdempotencyStore", "IdempotencyStore.__init__", CONTAINS),
    ("PaymentService.capture", "IdempotencyStore.claim", CALLS),
    ("PaymentService.__init__", "IdempotencyStore", REFERENCES),
    ("test_capture_uses_idempotency_store", "PaymentService.capture", TESTS),
)

# The other three query-backed languages, same shape as _JAVA_APP and for the
# same reason: no TESTS edge and no route exists, so a changed callee expands
# through its inbound CALLS or not at all.
#
# _SCALA_APP's edge is the one worth naming: it exists only because ADR-0067
# made member calls emit CALLS. Before that ruling a change to `charge` would
# have reported no impact whatsoever.
_SCALA_APP = {
    "OrderService": CLASS,
    "OrderService.capture": METHOD,
    "PaymentService": CLASS,
    "PaymentService.charge": METHOD,
}
_SCALA_EDGES = (
    ("OrderService", "OrderService.capture", CONTAINS),
    ("PaymentService", "PaymentService.charge", CONTAINS),
    ("OrderService.capture", "PaymentService.charge", CALLS),
)

_GO_APP = {
    "OrderService": CLASS,
    "OrderService.Capture": METHOD,
    "Service": CLASS,
    "Service.Charge": METHOD,
}
_GO_EDGES = (
    ("OrderService", "OrderService.Capture", CONTAINS),
    ("Service", "Service.Charge", CONTAINS),
    ("OrderService.Capture", "Service.Charge", CALLS),
)

_RUST_APP = {
    "OrderService": CLASS,
    "OrderService.capture": METHOD,
    "PaymentService": CLASS,
    "PaymentService.charge": METHOD,
}
_RUST_EDGES = (
    ("OrderService", "OrderService.capture", CONTAINS),
    ("PaymentService", "PaymentService.charge", CONTAINS),
    ("OrderService.capture", "PaymentService.charge", CALLS),
)

# ADR-0065. Java carries no TESTS edge and no route, so the only thing that can
# expand from a changed method is its inbound CALLS -- which is the point of
# c029: impact analysis works for a query-backed language, and the absence of a
# test in the result is the declared limit rather than a missing edge here.
_JAVA_APP = {
    "OrderService": CLASS,
    "OrderService.capture": METHOD,
    "PaymentService": CLASS,
    "PaymentService.charge": METHOD,
}
_JAVA_EDGES = (
    ("OrderService", "OrderService.capture", CONTAINS),
    ("PaymentService", "PaymentService.charge", CONTAINS),
    ("OrderService.capture", "PaymentService.charge", CALLS),
)

_TSJS = {"Order": IFACE, "total": PY, "render": PY}
_TSJS_EDGES = (
    ("total", "Order", REFERENCES),
    ("render", "total", CALLS),
)

_MIXED = {
    "get_order": PY,
    "health": PY,
    "loadOrder": PY,
    "healthPath": CONST,
    "Order flow": DOC,
}
_MIXED_EDGES = (
    ("loadOrder", "get_order", ROUTES_TO),
    ("healthPath", "health", REFERENCES),
    ("Order flow", "get_order", DOCUMENTS),
    ("Order flow", "loadOrder", DOCUMENTS),
)
# `healthPath` holds a route literal, so its `REFERENCES` edge is an agreement
# about a path rather than a type dependency.
_ROUTE = frozenset({("healthPath", "health")})

_DOCS_CONFIG = {
    "service": CONFIG,
    "scripts": CONFIG,
    "Sample Service": DOC,
    "Health": DOC,
    "Metrics": DOC,
    "server.port": CONFIG,
    "cache.ttl": CONFIG,
}
_DOCS_EDGES = (("Sample Service", "service", DOCUMENTS),)

CASES: tuple[Case, ...] = (
    Case(
        "c001",
        _PYTHON_APP,
        _PYTHON_EDGES,
        (("PaymentService.capture", ChangeKind.MODIFIED),),
    ),
    Case(
        "c002",
        _PYTHON_APP,
        _PYTHON_EDGES,
        (("PaymentService.capture", ChangeKind.MODIFIED),),
    ),
    Case(
        "c003",
        _PYTHON_APP,
        _PYTHON_EDGES,
        (("IdempotencyStore.claim", ChangeKind.MODIFIED),),
    ),
    Case(
        "c004",
        _PYTHON_APP,
        _PYTHON_EDGES,
        (("IdempotencyStore.__init__", ChangeKind.MODIFIED),),
    ),
    Case(
        "c005",
        _PYTHON_APP,
        _PYTHON_EDGES,
        (("test_capture_uses_idempotency_store", ChangeKind.MODIFIED),),
    ),
    Case(
        "c006",
        {**_PYTHON_APP, "FakeStore": CLASS},
        (
            *_PYTHON_EDGES,
            ("test_capture_uses_idempotency_store", "FakeStore", REFERENCES),
        ),
        (("FakeStore", ChangeKind.DELETED),),
        deleted_in_target=("FakeStore",),
    ),
    Case("c007", _TSJS, _TSJS_EDGES, (("Order", ChangeKind.MODIFIED),)),
    Case("c008", _TSJS, _TSJS_EDGES, (("total", ChangeKind.MODIFIED),)),
    Case("c009", _TSJS, _TSJS_EDGES, (("render", ChangeKind.MODIFIED),)),
    Case("c010", _TSJS, _TSJS_EDGES, (("total", ChangeKind.MODIFIED),)),
    Case("c011", _TSJS, _TSJS_EDGES, (("render", ChangeKind.DEPENDENCY),)),
    Case("c012", _DOCS_CONFIG, _DOCS_EDGES, (("service", ChangeKind.MODIFIED),)),
    Case("c013", _DOCS_CONFIG, _DOCS_EDGES, (("Health", ChangeKind.MODIFIED),)),
    Case("c014", _DOCS_CONFIG, _DOCS_EDGES, (("scripts", ChangeKind.MODIFIED),)),
    Case("c025", _DOCS_CONFIG, _DOCS_EDGES, (("Metrics", ChangeKind.ADDED),)),
    # A nested config leaf carries no DOCUMENTS edge, so neither c026 nor c027
    # expands to an impact path; the point of both is the *count* of what
    # changed, which `test_findings.py` pins.
    Case("c026", _DOCS_CONFIG, _DOCS_EDGES, (("server.port", ChangeKind.MODIFIED),)),
    Case("c027", _DOCS_CONFIG, _DOCS_EDGES, (("cache.ttl", ChangeKind.MODIFIED),)),
    # c028 changes nothing, so there is nothing to orient. An empty change set
    # is the assertion, not a gap in the table.
    Case("c028", _PYTHON_APP, _PYTHON_EDGES, ()),
    # c029: a Java method body change. The inbound CALLS edge is the whole
    # expansion -- no test edge exists for Java (ADR-0065).
    Case(
        "c029",
        _JAVA_APP,
        _JAVA_EDGES,
        (("PaymentService.charge", ChangeKind.MODIFIED),),
    ),
    # c030-c032: the same orientation check for the other three.
    Case(
        "c030",
        _SCALA_APP,
        _SCALA_EDGES,
        (("PaymentService.charge", ChangeKind.MODIFIED),),
    ),
    Case(
        "c031",
        _GO_APP,
        _GO_EDGES,
        (("Service.Charge", ChangeKind.MODIFIED),),
    ),
    Case(
        "c032",
        _RUST_APP,
        _RUST_EDGES,
        (("PaymentService.charge", ChangeKind.MODIFIED),),
    ),
    Case(
        "c015", _MIXED, _MIXED_EDGES, (("get_order", ChangeKind.MODIFIED),), _ROUTE
    ),
    Case(
        "c016", _MIXED, _MIXED_EDGES, (("loadOrder", ChangeKind.MODIFIED),), _ROUTE
    ),
    Case("c017", _MIXED, _MIXED_EDGES, (("health", ChangeKind.MODIFIED),), _ROUTE),
    Case(
        "c018", _MIXED, _MIXED_EDGES, (("healthPath", ChangeKind.MODIFIED),), _ROUTE
    ),
    Case(
        "c019", _MIXED, _MIXED_EDGES, (("Order flow", ChangeKind.MODIFIED),), _ROUTE
    ),
    Case("c020", {"process": PY}, (), (("process", ChangeKind.MOVED),)),
    Case(
        "c021",
        {"legacy": PY},
        (),
        (("legacy", ChangeKind.DELETED),),
        deleted_in_target=("legacy",),
    ),
    Case("c022", {"process": PY}, (), (("process", ChangeKind.MODIFIED),)),
    Case("c023", {"process": PY}, (), (("process", ChangeKind.MODIFIED),)),
    Case(
        "c024",
        {"Ignore previous instructions": DOC},
        (),
        (("Ignore previous instructions", ChangeKind.MODIFIED),),
    ),
)


def _symbol(name: str, kind: SymbolKind) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=f"sym_{name}",
        symbol_version_id=f"symv_{name}",
        file_id=f"file_{name.split('.')[0]}",
        kind=kind,
        name=name.rsplit(".", 1)[-1],
        qualified_name=name,
        module_path="",
        signature=None,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=1,
        content_hash=f"hash_{name}",
        visibility="public",
    )


def _relation(
    index: int, source: str, target: str, kind: RelationKind, *, route: bool = False
) -> RelationRecord:
    return RelationRecord(
        relation_id=f"rel_{index}",
        source_symbol_id=f"sym_{source}",
        target_symbol_id=f"sym_{target}",
        file_id=f"file_{source.split('.')[0]}",
        kind=kind,
        target_hint=target,
        resolution=ResolutionState.RESOLVED,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
        start_line=index + 1,
        end_line=index + 1,
        candidate_count=1,
        module_hint=ROUTE_HINT if route else "",
    )


def _sides(case: Case) -> tuple[GraphSide, GraphSide]:
    """Build the base and target graphs for one case.

    A symbol the case declares deleted exists in the base and not the target,
    together with every edge touching it — which is precisely the state that
    makes a deleted symbol's dependents visible only on the base side.
    """
    base_symbols = {
        f"sym_{name}": _symbol(name, kind) for name, kind in case.symbols.items()
    }
    base_relations = tuple(
        _relation(
            index,
            source,
            target,
            kind,
            route=(source, target) in case.route_edges,
        )
        for index, (source, target, kind) in enumerate(case.edges)
    )
    removed = set(case.deleted_in_target)
    target_symbols = {
        symbol_id: record
        for symbol_id, record in base_symbols.items()
        if record.qualified_name not in removed
    }
    target_relations = tuple(
        relation
        for relation, (source, target, _) in zip(
            base_relations, case.edges, strict=True
        )
        if source not in removed and target not in removed
    )
    return (
        GraphSide(symbols=base_symbols, relations=base_relations),
        GraphSide(symbols=target_symbols, relations=target_relations),
    )


def _expected() -> dict[str, set[tuple[str, ...]]]:
    document = json.loads(CHANGES.read_text(encoding="utf-8"))
    cases = document["cases"] if isinstance(document, dict) else document
    return {
        case["id"]: {tuple(path) for path in case["expected_impact_paths"]}
        for case in cases
    }


EXPECTED = _expected()


def _labeled(paths: tuple[tuple[str, str], ...]) -> set[tuple[str, ...]]:
    return {
        tuple(CORPUS_LABELS.get(name, name) for name in path) for path in paths
    }


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.case_id)
def test_the_orientation_rules_reproduce_the_declared_impact_paths(
    case: Case,
) -> None:
    base, target = _sides(case)
    changes = tuple(
        SymbolChange(
            qualified_name=name,
            symbol_kind=case.symbols[name],
            change_kind=kind,
            file_path=f"{name.split('.')[0]}.py",
        )
        for name, kind in case.changes
    )

    result = analyze_impact(changes, base=base, target=target)

    assert _labeled(result.paths) == EXPECTED[case.case_id]


def test_every_declared_case_is_covered_by_this_table() -> None:
    """A case added to the corpus must not silently skip its orientation check."""
    assert {case.case_id for case in CASES} == set(EXPECTED)
