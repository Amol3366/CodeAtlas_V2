"""Bounded traversal: termination, ordering, and honest truncation.

A traversal that silently truncates is worse than one that refuses: it reports a
partial answer in the same shape as a complete one. Every bound here is asserted
to *say so* when it bites.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from codeatlas.contracts import Derivation, RelationKind
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.domain.relations import RelationRecord, ResolutionState
from codeatlas.retrieval.graph import (
    MAX_ALLOWED_DEPTH,
    BoundedGraphTraversal,
    TraversalLimits,
)


def _edge(
    source: str,
    target: str | None,
    *,
    kind: RelationKind = RelationKind.CALLS,
    file_id: str = "file_1",
    start_line: int = 1,
) -> RelationRecord:
    return RelationRecord(
        relation_id=f"rel_{source}_{target}_{kind.value}_{start_line}",
        source_symbol_id=source,
        target_symbol_id=target,
        file_id=file_id,
        kind=kind,
        target_hint=target or "",
        resolution=(
            ResolutionState.RESOLVED if target else ResolutionState.UNRESOLVED
        ),
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
        start_line=start_line,
        end_line=start_line,
        candidate_count=1 if target else 0,
    )


@dataclass
class FakeRelations:
    """An in-memory graph that counts the queries traversal actually issues."""

    edges: list[RelationRecord] = field(default_factory=list)
    outgoing_calls: int = 0
    incoming_calls: int = 0

    def outgoing(
        self,
        snapshot_id: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        self.outgoing_calls += 1
        wanted = set(symbol_ids)
        return tuple(
            edge
            for edge in self.edges
            if edge.source_symbol_id in wanted
            and (kinds is None or edge.kind in set(kinds))
        )

    def incoming(
        self,
        snapshot_id: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        self.incoming_calls += 1
        wanted = set(symbol_ids)
        return tuple(
            edge
            for edge in self.edges
            if edge.target_symbol_id in wanted
            and (kinds is None or edge.kind in set(kinds))
        )


def _chain(length: int) -> FakeRelations:
    return FakeRelations(
        edges=[_edge(f"s{i}", f"s{i + 1}", start_line=i + 1) for i in range(length)]
    )


def test_an_empty_root_set_returns_nothing_without_querying() -> None:
    graph = FakeRelations()

    result = BoundedGraphTraversal(graph).expand("snap_1", [], "outgoing")

    assert result.edges == ()
    assert graph.outgoing_calls == 0


def test_depth_limits_how_far_traversal_reaches() -> None:
    graph = _chain(5)

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["s0"], "outgoing", limits=TraversalLimits(max_depth=2)
    )

    assert result.max_depth_reached == 2
    assert {edge.target_symbol_id for edge in result.edges} == {"s1", "s2"}


def test_hitting_the_depth_bound_is_reported() -> None:
    graph = _chain(5)

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["s0"], "outgoing", limits=TraversalLimits(max_depth=2)
    )

    assert "depth" in result.truncated_by
    assert result.truncated is True


def test_a_traversal_that_exhausts_the_graph_reports_no_truncation() -> None:
    graph = _chain(2)

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["s0"], "outgoing", limits=TraversalLimits(max_depth=5)
    )

    assert result.truncated_by == ()


def test_a_cycle_terminates() -> None:
    graph = FakeRelations(
        edges=[
            _edge("a", "b", start_line=1),
            _edge("b", "c", start_line=2),
            _edge("c", "a", start_line=3),
        ]
    )

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["a"], "outgoing", limits=TraversalLimits(max_depth=5)
    )

    assert result.visited_count == 3


def test_a_self_referential_node_is_normal_not_an_error() -> None:
    graph = FakeRelations(edges=[_edge("a", "a")])

    result = BoundedGraphTraversal(graph).expand("snap_1", ["a"], "outgoing")

    assert len(result.edges) == 1


def test_the_edge_bound_is_reported_when_hit() -> None:
    graph = FakeRelations(
        edges=[_edge("a", f"t{i}", start_line=i + 1) for i in range(10)]
    )

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["a"], "outgoing", limits=TraversalLimits(max_edges=3)
    )

    assert len(result.edges) == 3
    assert "edges" in result.truncated_by


def test_the_visited_bound_is_reported_when_hit() -> None:
    graph = FakeRelations(
        edges=[_edge("a", f"t{i}", start_line=i + 1) for i in range(10)]
    )

    result = BoundedGraphTraversal(graph).expand(
        "snap_1",
        ["a"],
        "outgoing",
        limits=TraversalLimits(max_visited=3, max_edges=50, max_paths=25),
    )

    assert "visited" in result.truncated_by


def test_the_path_bound_is_reported_when_hit() -> None:
    graph = FakeRelations(
        edges=[_edge("a", f"t{i}", start_line=i + 1) for i in range(10)]
    )

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["a"], "outgoing", limits=TraversalLimits(max_paths=2)
    )

    assert len(result.paths) == 2
    assert "paths" in result.truncated_by


def test_an_unresolved_edge_is_returned_but_expands_nothing() -> None:
    """An external import is a real edge with no far end to follow."""
    graph = FakeRelations(edges=[_edge("a", None, kind=RelationKind.IMPORTS)])

    result = BoundedGraphTraversal(graph).expand("snap_1", ["a"], "outgoing")

    assert len(result.edges) == 1
    assert result.visited_count == 1


def test_incoming_traversal_walks_the_other_direction() -> None:
    graph = _chain(3)

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["s3"], "incoming", limits=TraversalLimits(max_depth=5)
    )

    assert {edge.source_symbol_id for edge in result.edges} == {"s0", "s1", "s2"}


def test_kind_filtering_is_passed_through() -> None:
    graph = FakeRelations(
        edges=[
            _edge("a", "b", kind=RelationKind.CALLS, start_line=1),
            _edge("a", "c", kind=RelationKind.IMPORTS, start_line=2),
        ]
    )

    result = BoundedGraphTraversal(graph).expand(
        "snap_1", ["a"], "outgoing", kinds=[RelationKind.IMPORTS]
    )

    assert [edge.target_symbol_id for edge in result.edges] == ["c"]


def test_query_count_scales_with_depth_not_node_count() -> None:
    """One batched query per level; a per-node query would be the N+1 pattern."""
    graph = FakeRelations(
        edges=[
            *[_edge("root", f"a{i}", start_line=i + 1) for i in range(20)],
            *[_edge(f"a{i}", f"b{i}", start_line=i + 30) for i in range(20)],
        ]
    )

    result = BoundedGraphTraversal(graph).expand(
        "snap_1",
        ["root"],
        "outgoing",
        limits=TraversalLimits(
            max_depth=2, max_visited=200, max_edges=200, max_paths=25
        ),
    )

    assert result.visited_count > 20
    assert graph.outgoing_calls == 2


def test_repeated_traversal_returns_identical_results() -> None:
    graph = _chain(4)
    traversal = BoundedGraphTraversal(graph)

    first = traversal.expand("snap_1", ["s0"], "outgoing")
    second = traversal.expand("snap_1", ["s0"], "outgoing")

    assert first == second


def test_ordering_follows_file_path_then_line() -> None:
    graph = FakeRelations(
        edges=[
            _edge("a", "z", file_id="f2", start_line=1),
            _edge("a", "y", file_id="f1", start_line=9),
            _edge("a", "x", file_id="f1", start_line=2),
        ]
    )
    traversal = BoundedGraphTraversal(
        graph, paths_by_file={"f1": "src/a.py", "f2": "src/b.py"}
    )

    result = traversal.expand("snap_1", ["a"], "outgoing")

    assert [edge.target_symbol_id for edge in result.edges] == ["x", "y", "z"]


@pytest.mark.parametrize(
    "limits",
    [
        TraversalLimits(max_depth=MAX_ALLOWED_DEPTH + 1),
        TraversalLimits(max_visited=10_000),
        TraversalLimits(max_edges=1_000),
        TraversalLimits(max_paths=100),
        TraversalLimits(max_depth=0),
    ],
)
def test_an_over_large_limit_is_refused_not_clamped(limits: TraversalLimits) -> None:
    """A caller asking for depth 50 should be told no, not quietly given 5."""
    with pytest.raises(InvalidRequestError):
        BoundedGraphTraversal(FakeRelations()).expand(
            "snap_1", ["a"], "outgoing", limits=limits
        )
