"""Graph questions answered from stored relations, never from a guess.

Each method resolves the root symbol exactly first — reusing
`ExactSymbolLookupService` rather than reimplementing resolution — then
traverses, then emits a `QueryResponse` through the shared `EvidenceBuilder`.

Four trust rules govern every answer here:

* A claim's derivation is the **weakest** derivation among the edges supporting
  it. One `MAY_CALL` in a path makes the whole path heuristic, because a chain
  is exactly as trustworthy as its least trustworthy link.
* A `DOCUMENTS` edge never supports a claim on its own. Prose that mentions a
  symbol is advisory discovery, not evidence about behavior.
* An ambiguous root abstains and lists the candidates. Picking the first would
  answer a question the user did not ask.
* Truncation becomes both a warning and a limitation, so an incomplete answer
  says that it is incomplete.

"No callers found" and "callers were not analyzed" are different statements, and
the summaries keep them apart.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.evidence import (
    EvidenceBuilder,
    EvidenceCandidate,
    snapshot_reference,
)
from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    Evidence,
    QueryResponse,
    RelationKind,
    RelationPath,
    RelationStep,
)
from codeatlas.domain.errors import (
    InvalidRequestError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
)
from codeatlas.domain.relations import (
    FIXTURE_HINT,
    HELPER_HINT,
    RelationRecord,
)
from codeatlas.domain.snapshot import Snapshot
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.retrieval.graph import (
    BoundedGraphTraversal,
    Direction,
    TraversalLimits,
    TraversalResult,
)
from codeatlas.storage.sqlite.stores import (
    EvidenceStore,
    FileStore,
    RelationStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)

MAX_QUERY_LENGTH: int = 512

PHASE_LIMITATION = (
    "Phase 3 resolves relations statically. Calls through a variable, dynamic"
    " attribute access, and computed imports are not represented."
)

# Ordered weakest-first, so the weakest derivation in a set is the earliest one.
_DERIVATION_STRENGTH: tuple[Derivation, ...] = (
    Derivation.UNSUPPORTED,
    Derivation.MODEL_GENERATED,
    Derivation.SEMANTIC_CANDIDATE,
    Derivation.LOW_CONFIDENCE_HEURISTIC,
    Derivation.HIGH_CONFIDENCE_HEURISTIC,
    Derivation.STATIC_RESOLVED,
    Derivation.DETERMINISTIC,
)


@dataclass(frozen=True)
class GraphQueryRequest:
    """A bounded request for one symbol's neighbourhood."""

    repository_id: str
    symbol: str
    request_id: str
    max_depth: int = 2
    limits: TraversalLimits | None = None


class GraphQueryService:
    """Answers "who calls this", "what does this import", and their siblings."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        relations: RelationStore,
        evidence: EvidenceStore | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._files = files
        self._symbols = symbols
        self._relations = relations
        # Passing the store through makes every graph answer's evidence
        # addressable afterwards, which is what a citation in the UI will need.
        self._evidence = EvidenceBuilder(files, evidence)

    def callers(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="incoming",
            kinds=(RelationKind.CALLS, RelationKind.MAY_CALL),
            noun="callers",
        )

    def callees(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="outgoing",
            kinds=(RelationKind.CALLS, RelationKind.MAY_CALL),
            noun="callees",
        )

    def dependencies(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="outgoing",
            kinds=(RelationKind.IMPORTS, RelationKind.REFERENCES),
            noun="dependencies",
        )

    def dependents(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="incoming",
            kinds=(RelationKind.IMPORTS, RelationKind.REFERENCES),
            noun="dependents",
        )

    def exports(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="outgoing",
            kinds=(RelationKind.EXPORTS,),
            noun="exports",
        )

    def related_tests(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="incoming",
            kinds=(RelationKind.TESTS,),
            noun="tests",
        )

    def related_documents(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="incoming",
            kinds=(RelationKind.DOCUMENTS,),
            noun="documents",
        )

    def trace(self, request: GraphQueryRequest) -> QueryResponse:
        return self._answer(
            request,
            direction="outgoing",
            kinds=(
                RelationKind.CALLS,
                RelationKind.MAY_CALL,
                RelationKind.IMPORTS,
                # ADR-0034. `ROUTES_TO` exists to model an HTTP boundary
                # (P4-05), and a flow question is the one question that most
                # needs to cross it: without this a trace stops at the frontend
                # caller and never reaches the handler it invokes, which is the
                # cross-language capability the `mixed_app` fixture exists to
                # demonstrate.
                RelationKind.ROUTES_TO,
            ),
            noun="flow",
        )

    def _answer(
        self,
        request: GraphQueryRequest,
        *,
        direction: Direction,
        kinds: Sequence[RelationKind],
        noun: str,
    ) -> QueryResponse:
        query = request.symbol.strip()
        if not query or len(query) > MAX_QUERY_LENGTH:
            raise InvalidRequestError(
                f"The symbol must be between 1 and {MAX_QUERY_LENGTH} characters."
            )

        repository = self._repositories.get(request.repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")

        snapshot = self._snapshots.get_active(request.repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot. Index it first."
            )

        started = time.perf_counter()
        roots = self._symbols.find_exact(snapshot.snapshot_id, query, 10)
        if not roots:
            return self._empty(
                request,
                snapshot,
                summary=(
                    f"CodeAtlas found no symbol matching '{query}' in the active"
                    " snapshot, so its {noun} could not be determined."
                ).replace("{noun}", noun),
                warnings=("NO_EXACT_SYMBOL_MATCH",),
                timing={"resolve": (time.perf_counter() - started) * 1000},
            )

        if len(roots) > 1:
            # Answering for one of several candidates would silently pick a
            # question the caller did not ask.
            names = ", ".join(sorted(symbol.qualified_name for symbol in roots))
            return self._empty(
                request,
                snapshot,
                summary=(
                    f"'{query}' is ambiguous in the active snapshot and matches"
                    f" {len(roots)} symbols: {names}. Ask again with a qualified"
                    " name."
                ),
                warnings=("SYMBOL_AMBIGUOUS",),
                timing={"resolve": (time.perf_counter() - started) * 1000},
            )

        root = roots[0]
        limits = request.limits or TraversalLimits(max_depth=request.max_depth)
        traversal = BoundedGraphTraversal(
            self._relations,
            paths_by_file={
                record.file_id: record.relative_path
                for record in self._files.list_for_snapshot(snapshot.snapshot_id)
            },
        )
        result = traversal.expand(
            snapshot.snapshot_id, [root.symbol_id], direction, kinds, limits
        )
        traverse_ms = (time.perf_counter() - started) * 1000

        if not result.edges:
            return self._empty(
                request,
                snapshot,
                summary=(
                    f"{root.qualified_name} has no {noun} recorded in the active"
                    " snapshot."
                ),
                warnings=(f"NO_RELATIONS_{noun.upper()}",),
                timing={"traverse": traverse_ms},
            )

        return self._respond(
            request=request,
            repository_root=Path(repository.canonical_root),
            snapshot=snapshot,
            root=root,
            result=result,
            noun=noun,
            direction=direction,
            timing={"traverse": traverse_ms},
        )

    def _respond(
        self,
        *,
        request: GraphQueryRequest,
        repository_root: Path,
        snapshot: Snapshot,
        root: SymbolRecord,
        result: TraversalResult,
        noun: str,
        direction: Direction,
        timing: dict[str, float],
    ) -> QueryResponse:
        symbols_by_id = {
            symbol.symbol_id: symbol
            for symbol in self._symbols.list_for_snapshot(snapshot.snapshot_id)
        }
        started = time.perf_counter()
        # One candidate per edge, plus a second for a route's destination.
        # `owners` keeps the edge each candidate belongs to, because the two
        # lists stop being 1:1 once a `ROUTES_TO` edge contributes both.
        candidates: list[EvidenceCandidate] = []
        owners: list[RelationRecord] = []
        for edge in result.edges:
            candidates.append(
                EvidenceCandidate(
                    file_id=edge.file_id,
                    start_line=edge.start_line,
                    end_line=edge.end_line,
                    symbol=_cited_symbol(edge, symbols_by_id),
                    derivation=edge.derivation,
                    confidence=edge.confidence,
                )
            )
            owners.append(edge)

            destination = _route_destination(edge, symbols_by_id)
            if destination is not None:
                # ADR-0055. A route is the one relation whose reference site
                # alone cannot show what the flow reaches: the literal sits in
                # the caller's file and names a handler in another language's.
                # ADR-0034 added `ROUTES_TO` to `trace` precisely to cross that
                # boundary, so citing only the near side answers half the
                # question. This is the ADR-0019 `EXPORTS` carve-out applied to
                # the other relation that *names* its target.
                candidates.append(
                    EvidenceCandidate(
                        file_id=destination.file_id,
                        start_line=destination.start_line,
                        end_line=destination.end_line,
                        symbol=destination.qualified_name,
                        derivation=edge.derivation,
                        confidence=edge.confidence,
                    )
                )
                owners.append(edge)

        built = self._evidence.build(
            repository_root=repository_root,
            snapshot=snapshot,
            candidates=candidates,
        )
        timing["evidence"] = (time.perf_counter() - started) * 1000

        warnings = list(built.warnings)
        limitations = [PHASE_LIMITATION]
        for reason in result.truncated_by:
            warnings.append(f"GRAPH_TRUNCATED_{reason.upper()}")
            limitations.append(
                f"The {noun} answer is incomplete: the {reason} bound was reached."
            )

        pairs = [(owners[index], item) for index, item in built.items]
        if not pairs:
            return self._empty(
                request,
                snapshot,
                summary=(
                    f"{root.qualified_name} has {len(result.edges)} recorded"
                    f" {noun}, but none could be cited against the current files."
                ),
                warnings=tuple(warnings),
                timing=timing,
                stale=built.stale,
            )

        claims = self._claims(root, pairs, symbols_by_id, noun, direction)
        # Every graph answer carries its relations structurally. The traversal
        # already computes these paths for every query; only `trace` used to
        # keep them, so `callers`, `dependencies`, `exports`, and
        # `related_tests` returned prose and evidence with no machine-readable
        # statement of what relates to what. Additive per ADR-0004 — the field
        # has always existed and clients that ignore it are unaffected.
        relation_paths = self._paths(result, built.evidence, symbols_by_id)

        # Some edge was counted and claimed but reached no path. A path needs
        # resolved endpoints, and an edge to an unresolved target -- a browser
        # global, a third-party callable -- has none, so this is expected and
        # not an error.
        #
        # Saying so is the point (Section 4.1). The summary counts *edges* and
        # `relation_paths` carries *paths*, so without this the two disagree
        # silently: `loadOrder` reports three flow relations and one path, and
        # a client reading the structured field has no way to tell that two
        # were inexpressible rather than absent (ADR-0034).
        #
        # Compared by count rather than identity because a path withholds all
        # its steps when any one loses its evidence, so an edge can vanish
        # without being individually identifiable here.
        pathed_steps = sum(len(path.steps) for path in relation_paths)
        if len(result.edges) > pathed_steps:
            warnings.append("RELATION_PATH_UNRESOLVED")

        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=snapshot_reference(snapshot, stale=built.stale),
            answer=Answer(
                summary=(
                    f"{root.qualified_name} has {len(pairs)} {noun} in the active"
                    " snapshot."
                ),
                claims=claims,
            ),
            evidence=list(built.evidence),
            relation_paths=relation_paths,
            warnings=warnings,
            limitations=limitations,
            timing_ms=timing,
        )

    def _claims(
        self,
        root: SymbolRecord,
        pairs: Sequence[tuple[RelationRecord, Evidence]],
        symbols_by_id: dict[str, SymbolRecord],
        noun: str,
        direction: Direction,
    ) -> list[Claim]:
        inbound = direction == "incoming"
        claims: list[Claim] = []
        # One claim per *edge*, not per citation. A route contributes two
        # citations — the literal and the handler it names — and they support
        # the same single assertion, so emitting a claim each would state that
        # assertion twice (ADR-0055).
        merged: list[tuple[RelationRecord, list[Evidence]]] = []
        for edge, evidence in pairs:
            if merged and merged[-1][0] is edge:
                merged[-1][1].append(evidence)
            else:
                merged.append((edge, [evidence]))

        for index, (edge, evidence_items) in enumerate(merged):
            evidence = evidence_items[0]
            if edge.kind is RelationKind.DOCUMENTS:
                # Advisory discovery only. It travels as evidence, never as the
                # sole support for a claim.
                continue

            # The "other party" is whichever end of the edge is not the root.
            # For an inbound question — who calls this — that is the *source*;
            # taking the target would make every answer read "X calls X".
            other = (
                _label(edge.source_symbol_id, symbols_by_id)
                if inbound
                else _label(edge.target_symbol_id, symbols_by_id)
                or edge.target_hint
            )
            if not other:
                other = edge.target_hint or edge.source_symbol_id

            # …except beyond the first hop, where that premise fails: traversal
            # runs to `max_depth` 2, so an edge may touch neither end of the
            # root. Rendering such an edge against the root's name asserts a
            # direct relationship its own cited line disproves — the line shows
            # a call to the *intermediate*. `relation_paths` always carried the
            # true path; only this prose overstated it (ADR-0052).
            intermediate = None
            if root.symbol_id not in (edge.source_symbol_id, edge.target_symbol_id):
                intermediate = (
                    _label(edge.target_symbol_id, symbols_by_id)
                    if inbound
                    else _label(edge.source_symbol_id, symbols_by_id)
                ) or edge.target_hint

            claims.append(
                Claim(
                    claim_id=f"c{index + 1}",
                    text=claim_text(
                        edge=edge,
                        other=other,
                        root_name=root.qualified_name,
                        file_path=evidence.file_path,
                        start_line=evidence.start_line,
                        inbound=inbound,
                        intermediate=intermediate,
                    ),
                    derivation=edge.derivation,
                    confidence=edge.confidence,
                    evidence_ids=[item.evidence_id for item in evidence_items],
                )
            )
        return claims

    def _paths(
        self,
        result: TraversalResult,
        evidence: Sequence[Evidence],
        symbols_by_id: dict[str, SymbolRecord],
    ) -> list[RelationPath]:
        by_region = {
            (item.file_path, item.start_line, item.end_line): item
            for item in evidence
        }
        paths: list[RelationPath] = []
        for path in result.paths:
            steps: list[RelationStep] = []
            for edge in path:
                match = next(
                    (
                        item
                        for key, item in by_region.items()
                        if key[1] == edge.start_line and key[2] == edge.end_line
                    ),
                    None,
                )
                if match is None:
                    # A step whose evidence was dropped cannot be shown; the
                    # whole path is withheld rather than shown with a gap.
                    steps = []
                    break
                steps.append(
                    RelationStep(
                        source=_label(edge.source_symbol_id, symbols_by_id)
                        or edge.source_symbol_id,
                        kind=edge.kind,
                        target=_label(edge.target_symbol_id, symbols_by_id)
                        or edge.target_hint,
                        derivation=edge.derivation,
                        confidence=edge.confidence,
                        evidence_id=match.evidence_id,
                    )
                )
            if steps:
                paths.append(RelationPath(steps=steps))
        return paths

    def _empty(
        self,
        request: GraphQueryRequest,
        snapshot: Snapshot,
        *,
        summary: str,
        warnings: Sequence[str],
        timing: dict[str, float],
        stale: bool = False,
    ) -> QueryResponse:
        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=snapshot_reference(snapshot, stale=stale),
            answer=Answer(summary=summary, claims=[]),
            evidence=[],
            warnings=list(warnings),
            limitations=[PHASE_LIMITATION],
            timing_ms=timing,
        )


def weakest_derivation(derivations: Sequence[Derivation]) -> Derivation:
    """Return the least trustworthy derivation in a set.

    A path is exactly as trustworthy as its weakest link, so this is what a
    claim spanning several edges must report.
    """
    if not derivations:
        return Derivation.UNSUPPORTED
    return min(derivations, key=_DERIVATION_STRENGTH.index)


def _cited_symbol(
    edge: RelationRecord, symbols_by_id: dict[str, SymbolRecord]
) -> str:
    """Name the symbol whose definition the edge's cited range actually covers.

    Almost every relation cites a *reference site* — a call, an import, a name
    use — and that line sits inside the source symbol, so the source is the
    right label. `EXPORTS` is the exception: it cites the exported symbol's own
    definition (`export interface Order` is `Order`'s range, not the module's),
    so labelling it with the exporting module named one symbol while showing
    another. Evidence whose label contradicts its own line range is the defect
    ADR-0016 named on the `related_tests` surface, and the product's whole claim
    is that a reader can verify what they are shown.
    """
    if edge.kind is RelationKind.EXPORTS:
        return _label(edge.target_symbol_id, symbols_by_id) or edge.target_hint or ""
    return _label(edge.source_symbol_id, symbols_by_id)


def _label(symbol_id: str | None, symbols_by_id: dict[str, SymbolRecord]) -> str:
    if symbol_id is None:
        return ""
    symbol = symbols_by_id.get(symbol_id)
    return symbol.qualified_name if symbol is not None else ""


# How a mediated `TESTS` edge was derived, in the words the sentence uses.
# Keyed on `module_hint` rather than `derivation`: a derivation is a strength,
# and a strength cannot name the path an edge came from. See ADR-0016.
_MEDIATION: dict[str, str] = {
    FIXTURE_HINT: "a fixture",
    HELPER_HINT: "a helper",
}


def _route_destination(
    edge: RelationRecord,
    symbols_by_id: dict[str, SymbolRecord],
) -> SymbolRecord | None:
    """The handler a route reaches, when the edge is a resolved route.

    `None` for every other relation kind, and for an unresolved route — a route
    to a handler nothing resolved has no definition to cite, and inventing one
    is the failure this product exists to refuse (ADR-0055).
    """
    if edge.kind is not RelationKind.ROUTES_TO or edge.target_symbol_id is None:
        return None
    return symbols_by_id.get(edge.target_symbol_id)


def claim_text(
    *,
    edge: RelationRecord,
    other: str,
    root_name: str,
    file_path: str,
    start_line: int,
    inbound: bool,
    intermediate: str | None = None,
) -> str:
    """The sentence one claim renders.

    A `TESTS` edge reached through a fixture parameter or a helper call names a
    test worth running, but it cannot show that the test covers the symbol --
    its citation is the mediating line, which never mentions the target. So it
    is reported and cited, and worded so it does not assert what it cannot
    support.

    `intermediate` applies the same rule to distance. Traversal runs to
    `max_depth` 2, so an answer routinely contains an edge touching *neither*
    end of the root; its citation is that edge's own line, which shows a call
    to the intermediate and not to the root. Naming the root as though the edge
    reached it directly asserts a relationship the cited line cannot support
    (ADR-0052). `None` means the edge is incident to the root and the direct
    wording is correct -- which is the common case, and is left untouched.
    """
    citation = f" at {file_path}:{start_line}."
    mediation = (
        _MEDIATION.get(edge.module_hint)
        if edge.kind is RelationKind.TESTS
        else None
    )
    if mediation is not None:
        subject, obj = (other, root_name) if inbound else (root_name, other)
        return (
            f"{subject} may exercise {obj} indirectly,"
            f" through {mediation},{citation}"
        )

    if intermediate is not None:
        subject, obj = (other, root_name) if inbound else (root_name, other)
        return (
            f"{subject} reaches {obj} indirectly,"
            f" through {intermediate},{citation}"
        )

    if inbound:
        return f"{other} {_verb(edge.kind)} {root_name}{citation}"
    return f"{root_name} {_verb(edge.kind)} {other}{citation}"


def _verb(kind: RelationKind) -> str:
    return {
        RelationKind.CALLS: "calls",
        RelationKind.MAY_CALL: "may call",
        RelationKind.IMPORTS: "imports",
        RelationKind.EXPORTS: "exports",
        RelationKind.INHERITS: "inherits from",
        RelationKind.IMPLEMENTS: "implements",
        RelationKind.REFERENCES: "references",
        RelationKind.TESTS: "tests",
        RelationKind.DOCUMENTS: "documents",
        RelationKind.CONTAINS: "contains",
        # Without this a route read "loadOrder relates to get_order" — the
        # fallback, on the one relation whose whole point is that it crosses an
        # HTTP boundary. It was never reached before ADR-0055, because the
        # route's claim was being dropped entirely.
        RelationKind.ROUTES_TO: "routes to",
    }.get(kind, "relates to")
