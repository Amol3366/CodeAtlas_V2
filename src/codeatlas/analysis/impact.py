"""Which symbols a change reaches, and how far away each one is.

This is the "what may be affected" half of the product contract, and it is
deliberately modest about what that means. An edge from a caller to a changed
function proves the caller *references* it. It does not prove the caller breaks,
and nothing here claims otherwise: the engine reports reachability with the
derivation of every edge it walked, and leaves the judgment to the finding rules.

The engine is handed two graphs and never asks Git anything. A base graph is
needed because a deleted symbol has no target-side edges at all — its dependents
are visible only in the state where it still existed — and because a dependency
that appeared between the two sides is a fact about the pair, not about either
one alone.

Orientation is pinned rather than incidental. A path reads ``[changed, other]``,
because the reader asked about the change. The exception is a change that *is* a
new dependency, where the thing depended upon leads: the interesting sentence is
"total is now used by render", not the reverse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from codeatlas.contracts import (
    ChangeKind,
    Derivation,
    GapReason,
    GapReasonCode,
    RelationKind,
    SymbolKind,
)
from codeatlas.domain.change import SymbolChange
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.domain.relations import (
    FIXTURE_HINT,
    HELPER_HINT,
    ROUTE_HINT,
    RelationRecord,
    ResolutionState,
)
from codeatlas.domain.symbols import SymbolRecord

MAX_ALLOWED_DEPTH: Final[int] = 5
MAX_ALLOWED_VISITED: Final[int] = 1_000
MAX_ALLOWED_EDGES: Final[int] = 1_000
MAX_ALLOWED_PATHS: Final[int] = 50

# A gap in test coverage is only meaningful for code. A document section or a
# configuration key is not untested; the question does not apply to it.
_UNTESTABLE_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {
        SymbolKind.MODULE,
        SymbolKind.DOCUMENT_SECTION,
        SymbolKind.CONFIG_KEY,
        SymbolKind.TEST,
        SymbolKind.FIXTURE,
    }
)

# Edges where the two ends merely *agree* about something rather than one
# depending on the other: a frontend and a handler naming one path, a document
# and the code it describes. Neither side is downstream, so a change to either
# can break the agreement and impact travels both ways.
#
# Every other edge is a dependency and travels one way only. Changing a callee
# affects its callers; changing a caller does not affect the callee, and
# reporting that it does would bury the real blast radius in noise.
_SYMMETRIC_KINDS: Final[frozenset[RelationKind]] = frozenset(
    {RelationKind.ROUTES_TO, RelationKind.DOCUMENTS}
)

# A constructor's change is visible to whoever references the class, so the
# class joins the walk. An ordinary method's is not: `IdempotencyStore.claim`
# changing tells you nothing about code that merely names `IdempotencyStore`.
_CONSTRUCTOR_NAMES: Final[frozenset[str]] = frozenset({"__init__", "constructor"})

# Edges that state where a symbol lives rather than what depends on it. A module
# is not affected by a function inside it changing, and following these walks
# every symbol back up to its file.
_STRUCTURAL_KINDS: Final[frozenset[RelationKind]] = frozenset(
    {RelationKind.CONTAINS, RelationKind.EXPORTS}
)

# An extraction intermediate: it records which fixture a test asked for, not
# what depends on what. Following it would report a fixture name as blast
# radius.
_NON_IMPACT_KINDS: Final[frozenset[RelationKind]] = frozenset(
    {RelationKind.CONSUMES_FIXTURE}
)


@dataclass(frozen=True)
class ImpactBounds:
    """Bounds for one impact expansion.

    The defaults are the blueprint's Section 4.8.5 impact limits. An over-large
    request is refused rather than clamped, matching the Phase 3 traversal: a
    caller asking for depth 99 has misunderstood something, and quietly giving
    them depth 5 would hide that.
    """

    max_depth: int = 3
    max_visited: int = 200
    max_edges: int = 200
    max_paths: int = 25

    def validate(self) -> None:
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
class GraphSide:
    """One side of a change: its symbols and the edges resolved within it.

    ``file_paths`` maps file ID to repository-relative path. Impact does not
    need it — an edge is between symbols — but architecture rules match on
    paths, and carrying the mapping with the graph keeps every consumer reading
    one description of a state rather than assembling its own.
    """

    symbols: Mapping[str, SymbolRecord]
    relations: tuple[RelationRecord, ...]
    file_paths: Mapping[str, str] = field(default_factory=dict)
    # Which files are test code, so a gap reason can tell a test's import from
    # a production one. Defaulted because impact itself never needs it — the
    # reason text does, and inventing "a test imports this" about a production
    # import would be a fabricated claim.
    test_file_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ImpactEdge:
    """One traversed edge, oriented for reading and labeled with its provenance."""

    source: str
    target: str
    kind: RelationKind
    derivation: Derivation
    confidence: float
    depth: int
    side: str


@dataclass(frozen=True)
class ImpactResult:
    """What the change reaches, and what the expansion could not cover."""

    edges: tuple[ImpactEdge, ...] = ()
    paths: tuple[tuple[str, str], ...] = ()
    test_gaps: tuple[str, ...] = ()
    test_gap_reasons: tuple[GapReason, ...] = ()
    unresolved_dependents: tuple[str, ...] = ()
    visited_count: int = 0
    max_depth_reached: int = 0
    truncated_by: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass
class _Adjacency:
    """Edges indexed by both endpoints, built once per side."""

    by_source: dict[str, list[RelationRecord]] = field(default_factory=dict)
    by_target: dict[str, list[RelationRecord]] = field(default_factory=dict)
    contains_parent: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, side: GraphSide) -> _Adjacency:
        built = cls()
        for relation in side.relations:
            if relation.resolution is not ResolutionState.RESOLVED:
                # An unresolved reference is a real fact about a file and is
                # reported elsewhere, but it reaches no symbol, so it cannot
                # carry impact.
                continue
            target = relation.target_symbol_id
            if target is None:
                continue
            built.by_source.setdefault(relation.source_symbol_id, []).append(relation)
            built.by_target.setdefault(target, []).append(relation)
            if relation.kind is RelationKind.CONTAINS:
                built.contains_parent[target] = relation.source_symbol_id
        return built

    def reaching(
        self, symbol_id: str, *, outbound_only: bool = False
    ) -> list[tuple[RelationRecord, str]]:
        """Edges along which a change to ``symbol_id`` travels.

        Inbound always: whoever references this symbol may be affected by it.
        Outbound only for a symmetric edge, or when the caller asks for the
        outbound view because the change *is* a new dependency.
        """
        found: list[tuple[RelationRecord, str]] = []
        for relation in self.by_source.get(symbol_id, ()):
            if relation.target_symbol_id is None:
                continue
            if outbound_only or _is_symmetric(relation):
                found.append((relation, relation.target_symbol_id))
        if outbound_only:
            return found
        for relation in self.by_target.get(symbol_id, ()):
            found.append((relation, relation.source_symbol_id))
        return found


def _is_symmetric(relation: RelationRecord) -> bool:
    """Whether both ends of this edge are equally exposed to the other changing.

    A route literal held in a constant resolves to `REFERENCES` rather than
    `ROUTES_TO` — a constant calls nothing — but it is still an agreement about
    a path, so it travels both ways like the `ROUTES_TO` it came from.
    """
    return relation.kind in _SYMMETRIC_KINDS or (
        relation.kind is RelationKind.REFERENCES
        and relation.module_hint == ROUTE_HINT
    )


def analyze_impact(
    changes: Sequence[SymbolChange],
    *,
    base: GraphSide,
    target: GraphSide,
    bounds: ImpactBounds | None = None,
) -> ImpactResult:
    """Expand every changed symbol into the symbols a stored edge connects it to."""
    limits = bounds or ImpactBounds()
    limits.validate()

    target_ids = _ids_by_name(target)
    base_ids = _ids_by_name(base)
    target_edges = _Adjacency.build(target)
    base_edges = _Adjacency.build(base)

    collected: dict[tuple[str, str], ImpactEdge] = {}
    truncated: list[str] = []
    visited: set[str] = set()
    depth_reached = 0

    for change in _ordered_changes(changes):
        # A deleted or moved-away symbol has no target-side edges. Its dependents
        # exist only in the state where it still did.
        from_base = change.change_kind in {ChangeKind.DELETED, ChangeKind.MOVED}
        side_name = "base" if from_base else "target"
        graph = base if from_base else target
        adjacency = base_edges if from_base else target_edges
        seed = (base_ids if from_base else target_ids).get(change.qualified_name)
        if seed is None:
            # Fall back to the other side: a moved symbol may be findable only
            # where it landed.
            seed = (target_ids if from_base else base_ids).get(change.qualified_name)
            if seed is None:
                continue
            graph = target if from_base else base
            adjacency = target_edges if from_base else base_edges
            side_name = "target" if from_base else "base"

        reached = _expand(
            seed=seed,
            change=change,
            graph=graph,
            adjacency=adjacency,
            limits=limits,
            collected=collected,
            truncated=truncated,
            side_name=side_name,
        )
        visited |= reached.visited
        depth_reached = max(depth_reached, reached.depth)

    edges = tuple(
        collected[key]
        for key in sorted(collected, key=lambda item: (collected[item].depth, item))
    )
    if len(edges) > limits.max_paths:
        _note(truncated, "paths")
        edges = edges[: limits.max_paths]

    warnings = tuple(f"GRAPH_TRUNCATED_{item.upper()}" for item in truncated)
    gaps, gap_reasons = _test_gaps(changes, target, target_ids, target_edges)
    return ImpactResult(
        edges=edges,
        paths=tuple((edge.source, edge.target) for edge in edges),
        test_gaps=gaps,
        test_gap_reasons=gap_reasons,
        unresolved_dependents=_unresolved_dependents(
            changes, base, base_ids, base_edges, target_ids
        ),
        visited_count=len(visited),
        max_depth_reached=depth_reached,
        truncated_by=tuple(truncated),
        warnings=warnings,
        limitations=tuple(
            f"Impact expansion stopped at the {item} bound; "
            "symbols beyond it were not examined."
            for item in truncated
        ),
    )


@dataclass
class _Reached:
    visited: set[str] = field(default_factory=set)
    depth: int = 0


def _expand(
    *,
    seed: str,
    change: SymbolChange,
    graph: GraphSide,
    adjacency: _Adjacency,
    limits: ImpactBounds,
    collected: dict[tuple[str, str], ImpactEdge],
    truncated: list[str],
    side_name: str,
) -> _Reached:
    """Breadth-first expansion from one changed symbol."""
    reached = _Reached(visited={seed})
    # A constructor's change is visible to whoever references the class, so the
    # class joins the first frontier and is *reported as* the changed symbol
    # there: the reader asked about the constructor, not about the class.
    roots = [seed]
    alias: dict[str, str] = {}
    parent = _constructor_container(seed, graph, adjacency)
    if parent is not None:
        roots.append(parent)
        reached.visited.add(parent)
        seed_name = _name(graph, seed)
        if seed_name is not None:
            alias[parent] = seed_name

    # A change that *is* a new dependency asks the opposite question: not "who
    # depends on this" but "what does this now depend on".
    outbound_only = change.change_kind is ChangeKind.DEPENDENCY

    # An edge is walked once. Without this, the second hop rediscovers the first
    # hop's edge from its far end and emits it reversed, which reads as though
    # the dependency ran the other way.
    walked: set[str] = set()
    frontier = list(dict.fromkeys(roots))
    for depth in range(1, limits.max_depth + 1):
        if not frontier:
            break
        reached.depth = max(reached.depth, depth)
        next_frontier: list[str] = []

        for near in frontier:
            for relation, far in _ordered(
                adjacency.reaching(near, outbound_only=outbound_only), graph
            ):
                if far == near or relation.relation_id in walked:
                    continue
                walked.add(relation.relation_id)
                if not _carries_impact(relation, depth):
                    continue
                if far in reached.visited:
                    # Already reached by an equal or shorter route. Emitting the
                    # edge anyway would add a second way to say the same thing
                    # and inflate the report without naming anything new.
                    continue

                source_name = (
                    alias.get(near) if depth == 1 else None
                ) or _name(graph, near)
                target_name = _name(graph, far)
                if source_name is None or target_name is None:
                    continue

                pair = (
                    (target_name, source_name)
                    if outbound_only
                    else (source_name, target_name)
                )
                if len(collected) >= limits.max_edges and pair not in collected:
                    _note(truncated, "edges")
                    break
                collected.setdefault(
                    pair,
                    ImpactEdge(
                        source=pair[0],
                        target=pair[1],
                        kind=relation.kind,
                        derivation=relation.derivation,
                        confidence=relation.confidence,
                        depth=depth,
                        side=side_name,
                    ),
                )

                if len(reached.visited) >= limits.max_visited:
                    _note(truncated, "visited")
                    continue
                reached.visited.add(far)
                next_frontier.append(far)

        if outbound_only:
            # The new dependency itself is the fact. What that dependency in
            # turn depends on is not something this change introduced.
            break
        frontier = sorted(dict.fromkeys(next_frontier))
        if frontier and depth == limits.max_depth:
            _note(truncated, "depth")
    return reached


def _carries_impact(relation: RelationRecord, depth: int) -> bool:
    """Whether this edge propagates impact at this distance.

    `CONTAINS` and `EXPORTS` never do. Both state where a symbol *lives* — its
    enclosing class, the module that publishes it — and a module is not affected
    by a function inside it changing. Following them walks every symbol back up
    to its file and turns every report into a list of modules.

    `TESTS` propagates only directly. A test of a caller of the changed symbol
    is not a related test, and listing it would make the tests section grow with
    distance rather than with relevance.
    """
    if relation.kind in _STRUCTURAL_KINDS or relation.kind in _NON_IMPACT_KINDS:
        return False
    return not (relation.kind is RelationKind.TESTS and depth > 1)


def _constructor_container(
    seed: str, graph: GraphSide, adjacency: _Adjacency
) -> str | None:
    symbol = graph.symbols.get(seed)
    if symbol is None or symbol.name not in _CONSTRUCTOR_NAMES:
        return None
    return adjacency.contains_parent.get(seed)


def _ordered(
    found: Sequence[tuple[RelationRecord, str]], graph: GraphSide
) -> list[tuple[RelationRecord, str]]:
    """Deterministic order: far-end name, then call site, then kind."""
    return sorted(
        found,
        key=lambda item: (
            _name(graph, item[1]) or "",
            item[0].start_line,
            item[0].kind.value,
            item[0].relation_id,
        ),
    )


def _ordered_changes(changes: Sequence[SymbolChange]) -> list[SymbolChange]:
    return sorted(changes, key=lambda item: (item.qualified_name, item.change_kind))


def _ids_by_name(side: GraphSide) -> dict[str, str]:
    """Map qualified name to symbol ID, keeping the first on a collision.

    A duplicate qualified name across files is possible and is not resolved
    here: picking one arbitrarily would make impact depend on iteration order.
    The first in sorted order wins, so the answer is at least stable.
    """
    found: dict[str, str] = {}
    for symbol_id in sorted(side.symbols):
        symbol = side.symbols[symbol_id]
        found.setdefault(symbol.qualified_name, symbol_id)
    return found


def _name(graph: GraphSide, symbol_id: str) -> str | None:
    symbol = graph.symbols.get(symbol_id)
    return symbol.qualified_name if symbol is not None else None


def _test_gaps(
    changes: Sequence[SymbolChange],
    target: GraphSide,
    ids: Mapping[str, str],
    adjacency: _Adjacency,
) -> tuple[tuple[str, ...], tuple[GapReason, ...]]:
    """Changed code symbols with no *qualifying* `TESTS` edge, and why.

    A qualifying edge is one the strict import-and-call pass produced. A
    fixture- or helper-mediated edge is reported as the reason the gap remains
    rather than as coverage that closes it: it is a candidate, and promoting a
    candidate to a fact is the one thing this product must not do.

    None of this claims a symbol is untested. Only executing the suite could.
    """
    gaps: list[str] = []
    reasons: list[GapReason] = []
    for change in changes:
        if change.symbol_kind in _UNTESTABLE_KINDS:
            continue
        if change.change_kind is ChangeKind.DELETED:
            continue
        symbol_id = ids.get(change.qualified_name)
        if symbol_id is None:
            continue
        if change.qualified_name in gaps:
            continue

        incoming = tuple(adjacency.by_target.get(symbol_id, ()))
        qualifying = [
            relation
            for relation in incoming
            if relation.kind is RelationKind.TESTS
            and relation.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
        ]
        if qualifying:
            continue

        gaps.append(change.qualified_name)
        reasons.append(_gap_reason(change.qualified_name, incoming, target))
    order = sorted(range(len(gaps)), key=lambda position: gaps[position])
    return (
        tuple(gaps[position] for position in order),
        tuple(reasons[position] for position in order),
    )


def _gap_reason(
    qualified_name: str, incoming: Sequence[RelationRecord], target: GraphSide
) -> GapReason:
    """The single strongest near-miss explaining one gap.

    Precedence runs from the strongest near-miss to the weakest, so the reason
    names the closest thing to coverage that was actually found.
    """

    def from_test(relation: RelationRecord) -> bool:
        """Is this edge's source inside test code?

        Without this, an ordinary production import would be reported as
        `IMPORTED_NOT_CALLED` — a reason whose text claims a *test* imports the
        symbol. That is a fabricated claim, not a weaker one.

        The check is on the file, not the symbol kind: a module-level
        `from orders import Order` in a test file has the MODULE symbol as its
        source, not a TEST symbol, so filtering by kind would miss the most
        common case entirely.
        """
        symbol = target.symbols.get(relation.source_symbol_id)
        return symbol is not None and symbol.file_id in target.test_file_ids

    weak = [
        relation
        for relation in incoming
        if relation.kind is RelationKind.TESTS
        and relation.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC
    ]
    fixture = [item for item in weak if item.module_hint == FIXTURE_HINT]
    helper = [item for item in weak if item.module_hint == HELPER_HINT]
    imports = [
        relation
        for relation in incoming
        if relation.kind is RelationKind.IMPORTS and from_test(relation)
    ]
    calls = [
        relation
        for relation in incoming
        if relation.kind is RelationKind.CALLS and from_test(relation)
    ]

    if fixture:
        return GapReason(
            qualified_name=qualified_name,
            reason=GapReasonCode.FIXTURE_MEDIATED_ONLY,
            explanation=(
                "A test reaches this only through a fixture. That is a "
                "candidate, not coverage."
            ),
            evidence_ids=[relation.relation_id for relation in fixture],
        )
    if helper:
        return GapReason(
            qualified_name=qualified_name,
            reason=GapReasonCode.HELPER_MEDIATED_ONLY,
            explanation=(
                "A test reaches this only through a test helper. That is a "
                "candidate, not coverage."
            ),
            evidence_ids=[relation.relation_id for relation in helper],
        )
    if imports and not calls:
        return GapReason(
            qualified_name=qualified_name,
            reason=GapReasonCode.IMPORTED_NOT_CALLED,
            explanation="A test imports this but never calls it.",
            evidence_ids=[relation.relation_id for relation in imports],
        )
    if calls and not imports:
        return GapReason(
            qualified_name=qualified_name,
            reason=GapReasonCode.CALLED_NOT_IMPORTED,
            explanation=(
                "A test calls this name without importing it, so the call may "
                "resolve to a different symbol."
            ),
            evidence_ids=[relation.relation_id for relation in calls],
        )
    return GapReason(
        qualified_name=qualified_name,
        reason=GapReasonCode.NO_TEST_FILE_REFERENCE,
        explanation="No test file references this symbol.",
        evidence_ids=[],
    )


def _unresolved_dependents(
    changes: Sequence[SymbolChange],
    base: GraphSide,
    base_ids: Mapping[str, str],
    base_edges: _Adjacency,
    target_ids: Mapping[str, str],
) -> tuple[str, ...]:
    """Symbols that referenced a deleted symbol and still exist afterwards.

    Their target-side references are `unresolved` — that is a recorded fact, not
    an inference. It is reported here rather than as a finding because the
    corpus does not expect one and finding precision is a gate metric.
    """
    found: list[str] = []
    for change in changes:
        if change.change_kind is not ChangeKind.DELETED:
            continue
        symbol_id = base_ids.get(change.qualified_name)
        if symbol_id is None:
            continue
        # A deleted container carries its subtree (folding rule 1), so a
        # dependent of any folded member is a dependent of this deletion.
        subtree = {symbol_id}
        frontier = [symbol_id]
        while frontier:
            for relation in base_edges.by_source.get(frontier.pop(), ()):
                member = relation.target_symbol_id
                if (
                    relation.kind is RelationKind.CONTAINS
                    and member is not None
                    and member not in subtree
                ):
                    subtree.add(member)
                    frontier.append(member)
        for member_id in sorted(subtree):
            for relation in base_edges.by_target.get(member_id, ()):
                if relation.source_symbol_id in subtree:
                    continue
                name = _name(base, relation.source_symbol_id)
                if name is None or name in found:
                    continue
                if name in target_ids:
                    found.append(name)
    return tuple(sorted(found))


def _note(truncated: list[str], reason: str) -> None:
    if reason not in truncated:
        truncated.append(reason)
