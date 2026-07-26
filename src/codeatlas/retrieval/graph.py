"""Bounded traversal of the stored relation graph.

Every bound exists because an unbounded one would eventually produce an answer
nobody can read from a query nobody can cancel. But a bound that silently
truncates is worse than no answer at all: it reports a partial result in the
same shape as a complete one. So every bound that is *hit* is named in
``truncated_by``, and callers are contractually required to surface it.

Limits above the declared maxima are rejected rather than clamped. A caller
asking for depth 50 has misunderstood something, and quietly giving them depth 5
would hide that.

Expansion is breadth-first with one batched store query per depth level, never
one per node. Traversal is the hottest path in this phase, and a per-node query
is the N+1 pattern `CLAUDE.md` Section 10.3 forbids.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from codeatlas.contracts import RelationKind
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.domain.relations import RelationRecord

Direction = Literal["outgoing", "incoming"]

MAX_ALLOWED_DEPTH: int = 5
MAX_ALLOWED_VISITED: int = 1_000
MAX_ALLOWED_EDGES: int = 200
MAX_ALLOWED_PATHS: int = 25


@dataclass(frozen=True)
class TraversalLimits:
    """Bounds for one traversal. Defaults are the product's normal answer size."""

    max_depth: int = 2
    max_visited: int = 200
    max_edges: int = 50
    max_paths: int = 10

    def validate(self) -> None:
        """Reject an over-large request instead of silently shrinking it."""
        for name, value, ceiling in (
            ("max_depth", self.max_depth, MAX_ALLOWED_DEPTH),
            ("max_visited", self.max_visited, MAX_ALLOWED_VISITED),
            ("max_edges", self.max_edges, MAX_ALLOWED_EDGES),
            ("max_paths", self.max_paths, MAX_ALLOWED_PATHS),
        ):
            if value < 1:
                raise InvalidRequestError(f"{name} must be at least 1.")
            if value > ceiling:
                raise InvalidRequestError(
                    f"{name} must not exceed {ceiling}; {value} was requested."
                )


@dataclass(frozen=True)
class TraversalResult:
    """What a traversal found, and what it had to leave out."""

    edges: tuple[RelationRecord, ...] = ()
    paths: tuple[tuple[RelationRecord, ...], ...] = ()
    visited_count: int = 0
    max_depth_reached: int = 0
    truncated_by: tuple[str, ...] = ()

    @property
    def truncated(self) -> bool:
        return bool(self.truncated_by)


class RelationSource(Protocol):
    """The slice of `RelationStore` traversal needs."""

    def outgoing(
        self,
        snapshot_id: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]: ...

    def incoming(
        self,
        snapshot_id: str,
        symbol_ids: Sequence[str],
        kinds: Sequence[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]: ...


@dataclass
class _Frontier:
    edges: list[RelationRecord] = field(default_factory=list)
    paths: dict[str, tuple[RelationRecord, ...]] = field(default_factory=dict)


class BoundedGraphTraversal:
    """Breadth-first expansion with reported truncation."""

    def __init__(
        self,
        relations: RelationSource,
        paths_by_file: Mapping[str, str] | None = None,
    ) -> None:
        self._relations = relations
        # Ordering keys on file path rather than file ID, so the same snapshot
        # produces the same answer regardless of how IDs happened to hash.
        self._paths_by_file = paths_by_file or {}

    def expand(
        self,
        snapshot_id: str,
        roots: Sequence[str],
        direction: Direction,
        kinds: Sequence[RelationKind] | None = None,
        limits: TraversalLimits | None = None,
    ) -> TraversalResult:
        bounds = limits or TraversalLimits()
        bounds.validate()

        if not roots:
            return TraversalResult()

        visited: set[str] = set(roots)
        frontier: list[str] = sorted(dict.fromkeys(roots))
        collected: list[RelationRecord] = []
        paths: dict[str, tuple[RelationRecord, ...]] = {}
        truncated: list[str] = []
        depth_reached = 0

        for depth in range(1, bounds.max_depth + 1):
            if not frontier:
                break

            # One query per level, for the whole frontier.
            found = (
                self._relations.outgoing(snapshot_id, frontier, kinds)
                if direction == "outgoing"
                else self._relations.incoming(snapshot_id, frontier, kinds)
            )
            if not found:
                break

            depth_reached = depth
            next_frontier: list[str] = []
            for relation in self._ordered(found):
                if len(collected) >= bounds.max_edges:
                    _note(truncated, "edges")
                    break

                collected.append(relation)
                far = self._far_end(relation, direction)
                if far is None:
                    continue

                near = self._near_end(relation, direction)
                prefix = paths.get(near, ())
                if far not in paths and len(paths) < bounds.max_paths:
                    paths[far] = (*prefix, relation)
                elif far not in paths:
                    _note(truncated, "paths")

                if far in visited:
                    # A cycle, or a node already reached by a shorter route.
                    # Both terminate here; a self-referential module is a normal
                    # case, not an error.
                    continue
                if len(visited) >= bounds.max_visited:
                    _note(truncated, "visited")
                    continue
                visited.add(far)
                next_frontier.append(far)

            if len(collected) >= bounds.max_edges and len(found) > len(collected):
                _note(truncated, "edges")

            frontier = sorted(dict.fromkeys(next_frontier))
            if frontier and depth == bounds.max_depth:
                _note(truncated, "depth")

        ordered_paths = tuple(
            paths[key]
            for key in sorted(paths, key=lambda item: (len(paths[item]), item))
        )
        return TraversalResult(
            edges=tuple(collected),
            paths=ordered_paths,
            visited_count=len(visited),
            max_depth_reached=depth_reached,
            truncated_by=tuple(truncated),
        )

    def _ordered(
        self, relations: Sequence[RelationRecord]
    ) -> list[RelationRecord]:
        """Deterministic order: file path, then start line, then kind."""
        return sorted(
            relations,
            key=lambda item: (
                self._paths_by_file.get(item.file_id, item.file_id),
                item.start_line,
                item.kind.value,
                item.relation_id,
            ),
        )

    @staticmethod
    def _far_end(relation: RelationRecord, direction: Direction) -> str | None:
        if direction == "outgoing":
            return relation.target_symbol_id
        return relation.source_symbol_id

    @staticmethod
    def _near_end(relation: RelationRecord, direction: Direction) -> str:
        if direction == "outgoing":
            return relation.source_symbol_id
        return relation.target_symbol_id or relation.source_symbol_id


def _note(truncated: list[str], reason: str) -> None:
    if reason not in truncated:
        truncated.append(reason)
