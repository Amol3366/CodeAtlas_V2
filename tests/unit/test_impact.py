"""Impact expansion over two relation graphs.

The engine never asks Git anything. It is handed a base graph and a target
graph and answers one question: given these changed symbols, which other
symbols does a stored edge connect them to, and how far away is each one.

Orientation is the subtle part and is pinned here per case. A path reads
``[changed, other]`` — the reader asked about the change, so the change comes
first — except when the change *is* a new dependency, where the thing depended
upon leads. Both rules are asserted, because a report that silently flips
direction is worse than one that omits the edge.
"""

from __future__ import annotations

from codeatlas.analysis.impact import (
    GraphSide,
    ImpactBounds,
    analyze_impact,
)
from codeatlas.contracts import (
    ChangeKind,
    Derivation,
    GapReason,
    GapReasonCode,
    RelationKind,
    SymbolKind,
)
from codeatlas.domain.change import SymbolChange
from codeatlas.domain.relations import (
    FIXTURE_HINT,
    HELPER_HINT,
    RelationRecord,
    ResolutionState,
)
from codeatlas.domain.symbols import SymbolRecord


def _symbol(
    name: str,
    *,
    kind: SymbolKind = SymbolKind.FUNCTION,
    file_id: str = "file_1",
) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=f"sym_{name}",
        symbol_version_id=f"symv_{name}",
        file_id=file_id,
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
    source: str,
    target: str | None,
    kind: RelationKind = RelationKind.CALLS,
    *,
    file_id: str = "file_1",
    line: int = 1,
    derivation: Derivation = Derivation.STATIC_RESOLVED,
    module_hint: str = "",
) -> RelationRecord:
    return RelationRecord(
        relation_id=f"rel_{source}_{kind.value}_{target}_{line}",
        source_symbol_id=f"sym_{source}",
        target_symbol_id=f"sym_{target}" if target is not None else None,
        file_id=file_id,
        kind=kind,
        target_hint=target or "",
        resolution=(
            ResolutionState.RESOLVED
            if target is not None
            else ResolutionState.UNRESOLVED
        ),
        derivation=derivation,
        confidence=0.95,
        start_line=line,
        end_line=line,
        candidate_count=1 if target is not None else 0,
        module_hint=module_hint,
    )


def _side(
    names: dict[str, SymbolKind],
    relations: list[RelationRecord],
    *,
    file_ids: dict[str, str] | None = None,
    test_file_ids: frozenset[str] = frozenset(),
) -> GraphSide:
    file_ids = file_ids or {}
    return GraphSide(
        symbols={
            f"sym_{name}": _symbol(name, kind=kind, file_id=file_ids.get(name, "file_1"))
            for name, kind in names.items()
        },
        relations=tuple(relations),
        test_file_ids=test_file_ids,
    )


def _change(
    name: str,
    kind: ChangeKind = ChangeKind.MODIFIED,
    *,
    symbol_kind: SymbolKind = SymbolKind.FUNCTION,
    file_path: str = "a.py",
) -> SymbolChange:
    return SymbolChange(
        qualified_name=name,
        symbol_kind=symbol_kind,
        change_kind=kind,
        file_path=file_path,
    )


def _paths(result: object) -> set[tuple[str, ...]]:
    return {tuple(path) for path in result.paths}  # type: ignore[attr-defined]


# --- Direct impact ------------------------------------------------------------


def test_an_inbound_caller_is_direct_impact() -> None:
    graph = _side(
        {"total": SymbolKind.FUNCTION, "render": SymbolKind.FUNCTION},
        [_relation("render", "total")],
    )

    result = analyze_impact([_change("total")], base=graph, target=graph)

    assert ("total", "render") in _paths(result)


def test_an_outbound_dependency_is_not_impact() -> None:
    """Changing a caller does not affect what it calls.

    The corpus is explicit about this — c001, c008, and c009 each declare only
    the inbound side — and the reason is that including outbound edges buries
    the real blast radius. `capture` calling `claim` is a fact about `capture`,
    not a consequence of changing it.
    """
    graph = _side(
        {"total": SymbolKind.FUNCTION, "helper": SymbolKind.FUNCTION},
        [_relation("total", "helper")],
    )

    result = analyze_impact([_change("total")], base=graph, target=graph)

    assert _paths(result) == set()


def test_an_agreement_edge_travels_both_ways() -> None:
    """A route or document edge has no downstream end; both sides can break."""
    graph = _side(
        {"loadOrder": SymbolKind.FUNCTION, "get_order": SymbolKind.FUNCTION},
        [_relation("loadOrder", "get_order", RelationKind.ROUTES_TO)],
    )

    forward = analyze_impact([_change("loadOrder")], base=graph, target=graph)
    backward = analyze_impact([_change("get_order")], base=graph, target=graph)

    assert ("loadOrder", "get_order") in _paths(forward)
    assert ("get_order", "loadOrder") in _paths(backward)


def test_a_tests_edge_reaches_only_the_symbol_it_tests() -> None:
    """c003: a test of a *caller* of the change is not a related test."""
    graph = _side(
        {
            "claim": SymbolKind.FUNCTION,
            "capture": SymbolKind.FUNCTION,
            "test_capture": SymbolKind.TEST,
        },
        [
            _relation("capture", "claim"),
            _relation("test_capture", "capture", RelationKind.TESTS, line=2),
        ],
    )

    result = analyze_impact([_change("claim")], base=graph, target=graph)

    assert ("claim", "capture") in _paths(result)
    assert ("capture", "test_capture") not in _paths(result)


def test_only_a_constructor_pulls_in_its_container() -> None:
    """c003 vs c004: `claim` changing says nothing about namers of the class."""
    graph = _side(
        {
            "Store": SymbolKind.CLASS,
            "Store.claim": SymbolKind.METHOD,
            "caller": SymbolKind.FUNCTION,
        },
        [
            _relation("Store", "Store.claim", RelationKind.CONTAINS),
            _relation("caller", "Store", RelationKind.REFERENCES, line=2),
        ],
    )

    result = analyze_impact(
        [_change("Store.claim", symbol_kind=SymbolKind.METHOD)],
        base=graph,
        target=graph,
    )

    assert _paths(result) == set()


def test_a_path_leads_with_the_changed_symbol(mixed_direction: None = None) -> None:
    """`render` calls `total`; asking about `total` answers `total` first."""
    graph = _side(
        {"total": SymbolKind.FUNCTION, "render": SymbolKind.FUNCTION},
        [_relation("render", "total")],
    )

    result = analyze_impact([_change("total")], base=graph, target=graph)

    assert ("render", "total") not in _paths(result)


def test_a_dependency_change_leads_with_the_dependency() -> None:
    """c011: `render` newly imports `total`, so `total` leads."""
    graph = _side(
        {"total": SymbolKind.FUNCTION, "render": SymbolKind.FUNCTION},
        [_relation("render", "total", RelationKind.IMPORTS)],
    )

    result = analyze_impact(
        [_change("render", ChangeKind.DEPENDENCY)], base=graph, target=graph
    )

    assert ("total", "render") in _paths(result)
    assert ("render", "total") not in _paths(result)


def test_an_edge_reaching_a_changed_symbols_container_counts() -> None:
    """c004: a constructor change surfaces referencers of its class."""
    graph = _side(
        {
            "IdempotencyStore": SymbolKind.CLASS,
            "IdempotencyStore.__init__": SymbolKind.METHOD,
            "PaymentService.__init__": SymbolKind.METHOD,
        },
        [
            _relation(
                "IdempotencyStore", "IdempotencyStore.__init__", RelationKind.CONTAINS
            ),
            _relation("PaymentService.__init__", "IdempotencyStore"),
        ],
    )

    result = analyze_impact(
        [_change("IdempotencyStore.__init__", symbol_kind=SymbolKind.METHOD)],
        base=graph,
        target=graph,
    )

    assert ("IdempotencyStore.__init__", "PaymentService.__init__") in _paths(result)


def test_an_unresolved_edge_produces_no_impact_path() -> None:
    graph = _side(
        {"total": SymbolKind.FUNCTION},
        [_relation("total", None, RelationKind.CALLS)],
    )

    result = analyze_impact([_change("total")], base=graph, target=graph)

    assert _paths(result) == set()


# --- Transitive expansion -----------------------------------------------------


def test_expansion_reaches_the_second_hop() -> None:
    """c007: `Order` reaches `total` directly and `render` one hop further."""
    graph = _side(
        {
            "Order": SymbolKind.INTERFACE,
            "total": SymbolKind.FUNCTION,
            "render": SymbolKind.FUNCTION,
        },
        [
            _relation("total", "Order", RelationKind.REFERENCES),
            _relation("render", "total"),
        ],
    )

    result = analyze_impact([_change("Order")], base=graph, target=graph)

    assert ("Order", "total") in _paths(result)
    assert ("total", "render") in _paths(result)


def test_each_hop_is_emitted_nearest_end_first() -> None:
    graph = _side(
        {"a": SymbolKind.FUNCTION, "b": SymbolKind.FUNCTION, "c": SymbolKind.FUNCTION},
        [_relation("b", "a"), _relation("c", "b")],
    )

    result = analyze_impact([_change("a")], base=graph, target=graph)

    assert ("a", "b") in _paths(result)
    assert ("b", "c") in _paths(result)


def test_a_cycle_terminates_rather_than_looping() -> None:
    graph = _side(
        {"a": SymbolKind.FUNCTION, "b": SymbolKind.FUNCTION},
        [_relation("a", "b"), _relation("b", "a", line=2)],
    )

    result = analyze_impact([_change("a")], base=graph, target=graph)

    assert ("a", "b") in _paths(result)


def test_depth_is_bounded_and_the_bound_is_reported() -> None:
    names = {f"s{index}": SymbolKind.FUNCTION for index in range(6)}
    chain = [_relation(f"s{index + 1}", f"s{index}") for index in range(5)]
    graph = _side(names, chain)

    result = analyze_impact(
        [_change("s0")], base=graph, target=graph, bounds=ImpactBounds(max_depth=2)
    )

    assert ("s0", "s1") in _paths(result)
    assert ("s2", "s3") not in _paths(result)
    assert any("depth" in item for item in result.truncated_by)


def test_truncation_produces_both_a_warning_and_a_limitation() -> None:
    names = {f"s{index}": SymbolKind.FUNCTION for index in range(6)}
    chain = [_relation(f"s{index + 1}", f"s{index}") for index in range(5)]
    graph = _side(names, chain)

    result = analyze_impact(
        [_change("s0")], base=graph, target=graph, bounds=ImpactBounds(max_depth=1)
    )

    assert any("GRAPH_TRUNCATED" in warning for warning in result.warnings)
    assert result.limitations


def test_an_over_large_bound_is_refused_rather_than_clamped() -> None:
    import pytest

    from codeatlas.domain.errors import InvalidRequestError

    graph = _side({"a": SymbolKind.FUNCTION}, [])

    with pytest.raises(InvalidRequestError):
        analyze_impact(
            [_change("a")], base=graph, target=graph, bounds=ImpactBounds(max_depth=99)
        )


# --- Deleted symbols ----------------------------------------------------------


def test_a_deleted_symbol_draws_its_impact_from_the_base_graph() -> None:
    base = _side(
        {"FakeStore": SymbolKind.CLASS, "test_capture": SymbolKind.TEST},
        [_relation("test_capture", "FakeStore")],
    )
    target = _side({"test_capture": SymbolKind.TEST}, [])

    result = analyze_impact(
        [_change("FakeStore", ChangeKind.DELETED, symbol_kind=SymbolKind.CLASS)],
        base=base,
        target=target,
    )

    assert ("FakeStore", "test_capture") in _paths(result)


def test_a_dependent_left_unresolved_by_a_deletion_is_reported() -> None:
    base = _side(
        {"FakeStore": SymbolKind.CLASS, "test_capture": SymbolKind.TEST},
        [_relation("test_capture", "FakeStore")],
    )
    target = _side({"test_capture": SymbolKind.TEST}, [])

    result = analyze_impact(
        [_change("FakeStore", ChangeKind.DELETED, symbol_kind=SymbolKind.CLASS)],
        base=base,
        target=target,
    )

    assert "test_capture" in result.unresolved_dependents


def test_a_deletion_reports_no_finding_of_its_own_here() -> None:
    """Findings are P4-07's job; impact reports facts, not conclusions."""
    base = _side(
        {"FakeStore": SymbolKind.CLASS, "test_capture": SymbolKind.TEST},
        [_relation("test_capture", "FakeStore")],
    )
    target = _side({"test_capture": SymbolKind.TEST}, [])

    result = analyze_impact(
        [_change("FakeStore", ChangeKind.DELETED, symbol_kind=SymbolKind.CLASS)],
        base=base,
        target=target,
    )

    assert not hasattr(result, "findings")


# --- Test gaps ----------------------------------------------------------------


def test_a_changed_symbol_without_an_inbound_tests_edge_is_a_gap() -> None:
    graph = _side({"total": SymbolKind.FUNCTION}, [])

    result = analyze_impact([_change("total")], base=graph, target=graph)

    assert "total" in result.test_gaps


def test_a_changed_symbol_with_an_inbound_tests_edge_is_not_a_gap() -> None:
    graph = _side(
        {"total": SymbolKind.FUNCTION, "test_total": SymbolKind.TEST},
        [
            _relation(
                "test_total",
                "total",
                RelationKind.TESTS,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
            )
        ],
    )

    result = analyze_impact([_change("total")], base=graph, target=graph)

    assert "total" not in result.test_gaps


def test_a_changed_test_is_never_its_own_coverage_gap() -> None:
    graph = _side({"test_total": SymbolKind.TEST}, [])

    result = analyze_impact(
        [_change("test_total", symbol_kind=SymbolKind.TEST)],
        base=graph,
        target=graph,
    )

    assert result.test_gaps == ()


def test_a_changed_document_is_never_a_coverage_gap() -> None:
    graph = _side({"Order flow": SymbolKind.DOCUMENT_SECTION}, [])

    result = analyze_impact(
        [_change("Order flow", symbol_kind=SymbolKind.DOCUMENT_SECTION)],
        base=graph,
        target=graph,
    )

    assert result.test_gaps == ()


# --- Gap reasons ----------------------------------------------------------------


def by_name(reasons: tuple[GapReason, ...], qualified_name: str) -> GapReason | None:
    for reason in reasons:
        if reason.qualified_name == qualified_name:
            return reason
    return None


def one(edges: tuple[object, ...], *, target: str) -> object:
    matches = [edge for edge in edges if edge.target == target]  # type: ignore[attr-defined]
    assert len(matches) == 1, matches
    return matches[0]


def _fixture_mediated_graph() -> GraphSide:
    """`test_orders.test_total` reaches `orders.Order` only through a fixture.

    The fixture calls `Order` directly (evidence the strict pass never sees,
    since the test itself names only the fixture), and the test's
    `CONSUMES_FIXTURE` edge records which fixture it asked for. A synthetic
    weak `TESTS` edge, tagged `FIXTURE_HINT`, is what Task 4's derivation pass
    would have produced from those two facts.
    """
    return _side(
        {
            "orders.Order": SymbolKind.CLASS,
            "order_fixture": SymbolKind.FIXTURE,
            "test_orders.test_total": SymbolKind.TEST,
        },
        [
            _relation("order_fixture", "orders.Order", RelationKind.CALLS),
            _relation(
                "test_orders.test_total",
                "order_fixture",
                RelationKind.CONSUMES_FIXTURE,
            ),
            _relation(
                "test_orders.test_total",
                "orders.Order",
                RelationKind.TESTS,
                derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                module_hint=FIXTURE_HINT,
            ),
        ],
        file_ids={
            "order_fixture": "file_test",
            "test_orders.test_total": "file_test",
        },
        test_file_ids=frozenset({"file_test"}),
    )


def analyze_fixture_mediated() -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    graph = _fixture_mediated_graph()
    result = analyze_impact(
        [_change("orders.Order", symbol_kind=SymbolKind.CLASS)],
        base=graph,
        target=graph,
    )
    return result.test_gaps, result.test_gap_reasons


def impact_edges_for_fixture_mediated() -> tuple[object, ...]:
    graph = _fixture_mediated_graph()
    result = analyze_impact(
        [_change("orders.Order", symbol_kind=SymbolKind.CLASS)],
        base=graph,
        target=graph,
    )
    return result.edges


def analyze_strictly_tested() -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    graph = _side(
        {"orders.Order": SymbolKind.CLASS, "test_orders.test_total": SymbolKind.TEST},
        [
            _relation(
                "test_orders.test_total",
                "orders.Order",
                RelationKind.TESTS,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
            )
        ],
    )
    result = analyze_impact(
        [_change("orders.Order", symbol_kind=SymbolKind.CLASS)],
        base=graph,
        target=graph,
    )
    return result.test_gaps, result.test_gap_reasons


def analyze_unreferenced() -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    graph = _side({"orders.Order": SymbolKind.CLASS}, [])
    result = analyze_impact(
        [_change("orders.Order", symbol_kind=SymbolKind.CLASS)],
        base=graph,
        target=graph,
    )
    return result.test_gaps, result.test_gap_reasons


def analyze_imported_not_called() -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    graph = _side(
        {"orders.Order": SymbolKind.CLASS, "test_orders": SymbolKind.MODULE},
        [_relation("test_orders", "orders.Order", RelationKind.IMPORTS)],
        file_ids={"test_orders": "file_test"},
        test_file_ids=frozenset({"file_test"}),
    )
    result = analyze_impact(
        [_change("orders.Order", symbol_kind=SymbolKind.CLASS)],
        base=graph,
        target=graph,
    )
    return result.test_gaps, result.test_gap_reasons


def analyze_fixture_and_bare_import() -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    graph = _fixture_mediated_graph()
    extra = _relation(
        "test_orders",
        "orders.Order",
        RelationKind.IMPORTS,
        file_id="file_test",
    )
    graph = GraphSide(
        symbols={
            **graph.symbols,
            "sym_test_orders": _symbol(
                "test_orders", kind=SymbolKind.MODULE, file_id="file_test"
            ),
        },
        relations=(*graph.relations, extra),
        test_file_ids=graph.test_file_ids,
    )
    result = analyze_impact(
        [_change("orders.Order", symbol_kind=SymbolKind.CLASS)],
        base=graph,
        target=graph,
    )
    return result.test_gaps, result.test_gap_reasons


def analyze_mixed() -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    """Three changed symbols, each landing in a different bucket."""
    graph = _side(
        {
            "orders.Order": SymbolKind.CLASS,
            "order_fixture": SymbolKind.FIXTURE,
            "test_orders.test_total": SymbolKind.TEST,
            "orders.Total": SymbolKind.FUNCTION,
            "orders.Helper": SymbolKind.FUNCTION,
            "test_orders": SymbolKind.MODULE,
        },
        [
            _relation("order_fixture", "orders.Order", RelationKind.CALLS),
            _relation(
                "test_orders.test_total",
                "order_fixture",
                RelationKind.CONSUMES_FIXTURE,
            ),
            _relation(
                "test_orders.test_total",
                "orders.Order",
                RelationKind.TESTS,
                derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                module_hint=FIXTURE_HINT,
            ),
            _relation(
                "test_orders.test_total",
                "orders.Total",
                RelationKind.TESTS,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                line=2,
            ),
            _relation(
                "test_orders", "orders.Helper", RelationKind.IMPORTS, line=3
            ),
        ],
        file_ids={
            "order_fixture": "file_test",
            "test_orders.test_total": "file_test",
            "test_orders": "file_test",
        },
        test_file_ids=frozenset({"file_test"}),
    )
    result = analyze_impact(
        [
            _change("orders.Order", symbol_kind=SymbolKind.CLASS),
            _change("orders.Total", symbol_kind=SymbolKind.FUNCTION),
            _change("orders.Helper", symbol_kind=SymbolKind.FUNCTION),
        ],
        base=graph,
        target=graph,
    )
    return result.test_gaps, result.test_gap_reasons


def test_a_fixture_mediated_symbol_stays_a_gap() -> None:
    # The governing principle: a weak edge explains a gap, it does not close it.
    gaps, _ = analyze_fixture_mediated()
    assert "orders.Order" in gaps


def test_a_fixture_mediated_gap_says_why() -> None:
    _, reasons = analyze_fixture_mediated()
    reason = by_name(reasons, "orders.Order")
    assert reason is not None
    assert reason.reason is GapReasonCode.FIXTURE_MEDIATED_ONLY
    assert reason.evidence_ids != []


def test_a_strictly_tested_symbol_is_not_a_gap() -> None:
    gaps, reasons = analyze_strictly_tested()
    assert "orders.Order" not in gaps
    assert by_name(reasons, "orders.Order") is None


def test_an_unreferenced_symbol_reports_no_reference() -> None:
    _, reasons = analyze_unreferenced()
    reason = by_name(reasons, "orders.Order")
    assert reason is not None
    assert reason.reason is GapReasonCode.NO_TEST_FILE_REFERENCE
    assert reason.evidence_ids == []


def test_an_imported_but_uncalled_symbol_says_so() -> None:
    _, reasons = analyze_imported_not_called()
    reason = by_name(reasons, "orders.Order")
    assert reason is not None
    assert reason.reason is GapReasonCode.IMPORTED_NOT_CALLED


def test_fixture_mediation_outranks_import_without_call() -> None:
    # Precedence runs strongest near-miss first.
    _, reasons = analyze_fixture_and_bare_import()
    reason = by_name(reasons, "orders.Order")
    assert reason is not None
    assert reason.reason is GapReasonCode.FIXTURE_MEDIATED_ONLY


def test_every_gap_has_exactly_one_reason() -> None:
    gaps, reasons = analyze_mixed()
    assert sorted(gaps) == sorted(reason.qualified_name for reason in reasons)


def test_a_weak_edge_appears_in_impact_with_its_derivation() -> None:
    edges = impact_edges_for_fixture_mediated()
    edge = one(edges, target="test_orders.test_total")
    assert edge.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC  # type: ignore[attr-defined]


def test_consumes_fixture_is_not_an_impact_edge() -> None:
    # It is an extraction intermediate, not a dependency.
    edges = impact_edges_for_fixture_mediated()
    assert all(
        edge.kind is not RelationKind.CONSUMES_FIXTURE  # type: ignore[attr-defined]
        for edge in edges
    )


# --- Determinism --------------------------------------------------------------


def test_the_same_inputs_produce_the_same_ordering() -> None:
    graph = _side(
        {
            "a": SymbolKind.FUNCTION,
            "b": SymbolKind.FUNCTION,
            "c": SymbolKind.FUNCTION,
        },
        [_relation("b", "a"), _relation("c", "a", line=2)],
    )

    first = analyze_impact([_change("a")], base=graph, target=graph)
    second = analyze_impact([_change("a")], base=graph, target=graph)

    assert first.paths == second.paths


def test_a_change_naming_no_known_symbol_yields_no_paths() -> None:
    graph = _side({"a": SymbolKind.FUNCTION}, [])

    result = analyze_impact([_change("nowhere")], base=graph, target=graph)

    assert _paths(result) == set()
