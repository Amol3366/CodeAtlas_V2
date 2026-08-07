"""Turning per-file references into snapshot-wide relations.

Resolution is recomputed for the whole snapshot on every index run. That is the
deliberate cost of the two-stage design, and it buys the property that matters:
an edge can never point at a symbol that has since moved or vanished, because no
edge is ever carried forward. ``CLAUDE.md`` Section 9's "necessary reverse
relations" requirement holds by construction rather than by bookkeeping.

The work is a pass over an in-memory name index built once per snapshot, so it
is O(references), not O(references x symbols).

The resolution order below is a *trust* ordering, not merely a search order.
Earlier steps use information the file itself states; later ones reach further
and are correspondingly weaker. Step 5 is the only one that crosses the whole
repository on a bare name, and it applies only when that name is globally
unique. A name matching several symbols is recorded as ambiguous with every
candidate counted — it never becomes a ``CALLS`` edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from codeatlas.contracts import Derivation, RelationKind, SymbolKind
from codeatlas.domain.ids import relation_id as build_relation_id
from codeatlas.domain.relations import (
    DERIVED_HINT,
    FIXTURE_HINT,
    HELPER_HINT,
    MENTION_HINT,
    ROUTE_HINT,
    RelationRecord,
    ResolutionState,
    SymbolReference,
)
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.extraction.routes import name_tokens, route_tokens, tokens_match

# Symbols that can answer a request. A route names a handler, never a module or
# a document heading that happens to share a word with it.
_HANDLER_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.FUNCTION, SymbolKind.METHOD}
)

# A constant states a path; it does not call one. The distinction is why
# `healthPath` references `health` rather than routing to it.
_VALUE_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.CONSTANT, SymbolKind.PROPERTY, SymbolKind.FIELD}
)

# Kinds a bare word in prose may not link to. A module and a document heading
# are named by ordinary English words far too often for a word match to be
# evidence, and a configuration key is matched by its dotted path instead.
_UNMENTIONABLE_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.MODULE, SymbolKind.CONFIG_KEY, SymbolKind.DOCUMENT_SECTION}
)

RESOLVER_VERSION: str = "1.2.0"

# Tried in order for a TypeScript/JavaScript specifier that names no extension.
_TSJS_EXTENSIONS: Final[tuple[str, ...]] = (
    ".ts",
    ".tsx",
    ".d.ts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)

_CONFIDENCE: Final[dict[Derivation, float]] = {
    Derivation.DETERMINISTIC: 1.0,
    Derivation.STATIC_RESOLVED: 0.95,
    Derivation.HIGH_CONFIDENCE_HEURISTIC: 0.7,
    Derivation.LOW_CONFIDENCE_HEURISTIC: 0.4,
}


@dataclass(frozen=True)
class ResolutionStats:
    """What one resolution pass concluded, counted rather than described."""

    references: int = 0
    resolved: int = 0
    external: int = 0
    unresolved: int = 0
    ambiguous: int = 0


@dataclass
class _Candidates:
    """Symbols a hint matched at one trust level."""

    symbols: tuple[SymbolRecord, ...] = ()

    @property
    def state(self) -> ResolutionState:
        if len(self.symbols) == 1:
            return ResolutionState.RESOLVED
        if len(self.symbols) > 1:
            return ResolutionState.AMBIGUOUS
        return ResolutionState.UNRESOLVED


@dataclass
class _Index:
    """Lookup tables built once per snapshot."""

    files_by_id: dict[str, FileRecord] = field(default_factory=dict)
    symbols_by_id: dict[str, SymbolRecord] = field(default_factory=dict)
    file_of_symbol: dict[str, str] = field(default_factory=dict)
    by_qualified: dict[str, list[SymbolRecord]] = field(default_factory=dict)
    by_name: dict[str, list[SymbolRecord]] = field(default_factory=dict)
    qualified_in_file: dict[tuple[str, str], list[SymbolRecord]] = field(
        default_factory=dict
    )
    name_in_file: dict[tuple[str, str], list[SymbolRecord]] = field(
        default_factory=dict
    )
    module_to_file: dict[str, str] = field(default_factory=dict)
    path_stem_to_file: dict[str, str] = field(default_factory=dict)


class SnapshotResolver:
    """Resolves a snapshot's references into relations, all at once."""

    def resolve(
        self,
        files: Sequence[FileRecord],
        symbols: Sequence[SymbolRecord],
        references: Sequence[SymbolReference],
    ) -> tuple[tuple[RelationRecord, ...], ResolutionStats]:
        index = _build_index(files, symbols)
        relations: list[RelationRecord] = []

        # Imports are resolved first because every other reference may need
        # them: "what does this name mean here" often answers to "whatever this
        # file imported".
        imports_by_file: dict[str, dict[str, SymbolRecord]] = {}
        import_relations: list[RelationRecord] = []
        for reference in references:
            if reference.kind is not RelationKind.IMPORTS:
                continue
            relation, target = _resolve_import(reference, index)
            import_relations.append(relation)
            if target is not None:
                imports_by_file.setdefault(reference.file_id, {})[
                    reference.target_hint
                ] = target

        relations.extend(import_relations)

        # Route and mention references name a path or a word rather than a
        # symbol, so the ordinary name-matching ladder cannot answer them.
        routes = [item for item in references if item.module_hint == ROUTE_HINT]
        mentions = [item for item in references if item.module_hint == MENTION_HINT]
        route_index = _RouteIndex.build(routes, index)

        for reference in references:
            if reference.kind is RelationKind.IMPORTS:
                continue
            if reference.module_hint == ROUTE_HINT:
                relations.append(_resolve_route(reference, index, route_index))
            elif reference.module_hint == MENTION_HINT:
                relations.append(_resolve_mention(reference, index))
            else:
                relations.append(
                    _resolve_reference(reference, index, imports_by_file)
                )

        relations.extend(_derive_test_edges(relations, index))
        relations.extend(_derive_fixture_test_edges(relations, index))
        relations.extend(_derive_helper_test_edges(relations, index))
        relations.extend(_derive_document_edges(routes, mentions, index, route_index))
        relations.sort(
            key=lambda item: (item.file_id, item.start_line, item.relation_id)
        )
        return tuple(relations), _count(relations, len(references))


def _count(
    relations: Sequence[RelationRecord], reference_count: int
) -> ResolutionStats:
    return ResolutionStats(
        references=reference_count,
        resolved=sum(
            item.resolution is ResolutionState.RESOLVED for item in relations
        ),
        external=sum(item.resolution is ResolutionState.EXTERNAL for item in relations),
        unresolved=sum(
            item.resolution is ResolutionState.UNRESOLVED for item in relations
        ),
        ambiguous=sum(
            item.resolution is ResolutionState.AMBIGUOUS for item in relations
        ),
    )


def _build_index(
    files: Sequence[FileRecord], symbols: Sequence[SymbolRecord]
) -> _Index:
    index = _Index()
    for record in files:
        index.files_by_id[record.file_id] = record
        stem = _path_stem(record.relative_path)
        index.path_stem_to_file.setdefault(stem, record.file_id)
        if record.language == "python":
            index.module_to_file.setdefault(
                _python_module(record.relative_path), record.file_id
            )

    for symbol in symbols:
        index.symbols_by_id[symbol.symbol_id] = symbol
        index.file_of_symbol[symbol.symbol_id] = symbol.file_id
        index.by_qualified.setdefault(symbol.qualified_name, []).append(symbol)
        index.by_name.setdefault(symbol.name, []).append(symbol)
        index.qualified_in_file.setdefault(
            (symbol.file_id, symbol.qualified_name), []
        ).append(symbol)
        index.name_in_file.setdefault((symbol.file_id, symbol.name), []).append(symbol)

    # Deterministic candidate order so an ambiguous result is reported the same
    # way on every run.
    for bucket in (
        *index.by_qualified.values(),
        *index.by_name.values(),
        *index.qualified_in_file.values(),
        *index.name_in_file.values(),
    ):
        bucket.sort(key=lambda symbol: (symbol.qualified_name, symbol.symbol_id))
    return index


def _resolve_import(
    reference: SymbolReference, index: _Index
) -> tuple[RelationRecord, SymbolRecord | None]:
    """Resolve an import to a repository file, or record it as external."""
    source_file = index.files_by_id.get(reference.file_id)
    target_file_id = (
        _resolve_module(reference.module_hint, source_file, index)
        if source_file is not None
        else None
    )

    if target_file_id is None:
        # A specifier naming nothing in this repository is a real fact about the
        # file. `node_modules` is never consulted, and neither is `tsconfig`.
        return (
            _build(
                reference,
                target=None,
                resolution=ResolutionState.EXTERNAL,
                derivation=Derivation.DETERMINISTIC,
                candidate_count=0,
            ),
            None,
        )

    candidates = _Candidates(
        tuple(index.name_in_file.get((target_file_id, reference.target_hint), ()))
    )
    if candidates.state is ResolutionState.RESOLVED:
        target = candidates.symbols[0]
        return (
            _build(
                reference,
                target=target,
                resolution=ResolutionState.RESOLVED,
                derivation=Derivation.STATIC_RESOLVED,
                candidate_count=1,
            ),
            target,
        )

    # The module exists but the name does not, or names several things. The
    # import statement is still a fact; the binding is not.
    return (
        _build(
            reference,
            target=None,
            resolution=candidates.state,
            derivation=Derivation.DETERMINISTIC,
            candidate_count=len(candidates.symbols),
        ),
        None,
    )


def _resolve_reference(
    reference: SymbolReference,
    index: _Index,
    imports_by_file: dict[str, dict[str, SymbolRecord]],
) -> RelationRecord:
    if reference.kind in {RelationKind.CONTAINS, RelationKind.EXPORTS}:
        return _resolve_structural(reference, index)

    for candidates in _candidate_levels(reference, index, imports_by_file):
        if candidates.state is ResolutionState.RESOLVED:
            return _build(
                reference,
                target=candidates.symbols[0],
                resolution=ResolutionState.RESOLVED,
                derivation=Derivation.STATIC_RESOLVED,
                candidate_count=1,
            )
        if candidates.state is ResolutionState.AMBIGUOUS:
            # Recorded, not chosen. A call that might mean three things is a
            # `MAY_CALL`; promoting it would be inventing certainty.
            return _build(
                reference,
                target=None,
                resolution=ResolutionState.AMBIGUOUS,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                candidate_count=len(candidates.symbols),
                kind=(
                    RelationKind.MAY_CALL
                    if reference.kind is RelationKind.CALLS
                    else reference.kind
                ),
            )

    return _build(
        reference,
        target=None,
        resolution=ResolutionState.UNRESOLVED,
        derivation=(
            Derivation.DETERMINISTIC
            if reference.kind is RelationKind.CONTAINS
            else Derivation.HIGH_CONFIDENCE_HEURISTIC
        ),
        candidate_count=0,
    )


def _resolve_structural(reference: SymbolReference, index: _Index) -> RelationRecord:
    """`CONTAINS` and `EXPORTS` are syntactic: the answer is in the same file."""
    key = (reference.file_id, reference.target_hint)
    candidates = _Candidates(
        tuple(index.qualified_in_file.get(key, ()))
        or tuple(index.name_in_file.get(key, ()))
    )
    resolved = candidates.state is ResolutionState.RESOLVED
    return _build(
        reference,
        target=candidates.symbols[0] if resolved else None,
        resolution=candidates.state,
        derivation=Derivation.DETERMINISTIC,
        candidate_count=len(candidates.symbols),
    )


def _candidate_levels(
    reference: SymbolReference,
    index: _Index,
    imports_by_file: dict[str, dict[str, SymbolRecord]],
) -> list[_Candidates]:
    """Candidate sets in trust order; the first non-empty one decides."""
    file_id = reference.file_id
    hint = reference.target_hint
    levels: list[_Candidates] = [
        # 1. Same file, by qualified name — `self.helper()` arrives here already
        #    qualified by its enclosing class.
        _Candidates(tuple(index.qualified_in_file.get((file_id, hint), ()))),
        # 2. Same file, module scope.
        _Candidates(tuple(index.name_in_file.get((file_id, hint), ()))),
    ]

    # 3. Imported into this file.
    imported = imports_by_file.get(file_id, {}).get(hint)
    levels.append(_Candidates((imported,) if imported is not None else ()))

    # 4. Same package: a sibling module's symbol of that name.
    source_file = index.files_by_id.get(file_id)
    if source_file is not None:
        package = _directory(source_file.relative_path)
        siblings = tuple(
            symbol
            for symbol in index.by_name.get(hint, ())
            if symbol.file_id != file_id
            and _directory(
                index.files_by_id[symbol.file_id].relative_path
                if symbol.file_id in index.files_by_id
                else ""
            )
            == package
        )
        levels.append(_Candidates(siblings))

    # 5. Repository-wide, and only when the name is globally unique.
    levels.append(_Candidates(tuple(index.by_qualified.get(hint, ()))))
    levels.append(_Candidates(tuple(index.by_name.get(hint, ()))))
    return levels


@dataclass
class _RouteIndex:
    """Who states each route, and who could be answering it."""

    owners: dict[str, list[SymbolRecord]] = field(default_factory=dict)

    @classmethod
    def build(
        cls, routes: Sequence[SymbolReference], index: _Index
    ) -> _RouteIndex:
        """Record which code symbols write each route literal down.

        A document that names a path is describing it, not serving it, so a
        document section is never recorded as an owner.
        """
        built = cls()
        for reference in routes:
            source = index.symbols_by_id.get(reference.source_symbol_id)
            if source is None or source.kind is SymbolKind.DOCUMENT_SECTION:
                continue
            bucket = built.owners.setdefault(reference.target_hint, [])
            if all(item.symbol_id != source.symbol_id for item in bucket):
                bucket.append(source)
        for bucket in built.owners.values():
            bucket.sort(key=lambda symbol: (symbol.qualified_name, symbol.symbol_id))
        return built

    def handlers(
        self, route: str, index: _Index, *, exclude_file_id: str
    ) -> tuple[SymbolRecord, ...]:
        """Functions whose name shares a word with the route's path segments.

        A symbol that writes the route down is excluded: it is the client that
        addresses the path, not the code that answers it. Without that rule a
        caller and its handler are indistinguishable, and both would be reported
        as ambiguous rather than one being reported as the answer.
        """
        tokens = route_tokens(route)
        if not tokens:
            return ()
        stated = {symbol.symbol_id for symbol in self.owners.get(route, ())}
        found = [
            symbol
            for symbol in index.symbols_by_id.values()
            if symbol.kind in _HANDLER_KINDS
            and symbol.file_id != exclude_file_id
            and symbol.symbol_id not in stated
            and tokens_match(tokens, name_tokens(symbol.name))
        ]
        found.sort(key=lambda symbol: (symbol.qualified_name, symbol.symbol_id))
        return tuple(found)


def _resolve_route(
    reference: SymbolReference, index: _Index, routes: _RouteIndex
) -> RelationRecord:
    """Match a route literal to the one function that plausibly answers it.

    Everything here is a heuristic and is labeled as one. A path string is not a
    routing table: the framework may mount it elsewhere, and no static rule can
    see that. What can be said honestly is that exactly one function in another
    file is named after this path, and that is what the edge records.
    """
    source = index.symbols_by_id.get(reference.source_symbol_id)
    candidates = _Candidates(
        routes.handlers(
            reference.target_hint, index, exclude_file_id=reference.file_id
        )
    )
    from_document = source is not None and source.kind is SymbolKind.DOCUMENT_SECTION

    if from_document:
        kind = RelationKind.DOCUMENTS
        derivation = Derivation.LOW_CONFIDENCE_HEURISTIC
    else:
        # A constant holds a path; it does not request one.
        kind = (
            RelationKind.REFERENCES
            if source is not None and source.kind in _VALUE_KINDS
            else RelationKind.ROUTES_TO
        )
        derivation = Derivation.HIGH_CONFIDENCE_HEURISTIC

    resolved = candidates.state is ResolutionState.RESOLVED
    return _build(
        reference,
        target=candidates.symbols[0] if resolved else None,
        resolution=candidates.state,
        derivation=derivation,
        candidate_count=len(candidates.symbols),
        kind=kind,
    )


def _resolve_mention(reference: SymbolReference, index: _Index) -> RelationRecord:
    """Link a word a document used to a symbol named exactly that.

    Comparison is case-insensitive and whole-word, and the weakest derivation in
    the model is used, because "the document contains this word" is genuinely
    weak evidence. Modules, configuration keys, and headings are excluded: they
    are named by ordinary English far too often for a word to mean anything.
    """
    word = reference.target_hint.lower()
    candidates = _Candidates(
        tuple(
            symbol
            for symbol in index.symbols_by_id.values()
            if symbol.kind not in _UNMENTIONABLE_KINDS
            and symbol.file_id != reference.file_id
            and symbol.name.lower() == word
        )
    )
    resolved = candidates.state is ResolutionState.RESOLVED
    return _build(
        reference,
        target=candidates.symbols[0] if resolved else None,
        resolution=candidates.state,
        derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        candidate_count=len(candidates.symbols),
        kind=RelationKind.DOCUMENTS,
    )


def _derive_document_edges(
    routes: Sequence[SymbolReference],
    mentions: Sequence[SymbolReference],
    index: _Index,
    route_index: _RouteIndex,
) -> list[RelationRecord]:
    """Document edges that no single reference states.

    Two rules, both needing more than one reference to see:

    * a document naming a path also describes the code that *writes* that path,
      which is known only by comparing this document against every other file;
    * a document names a configuration key when every dotted segment of that
      key appears in the section as a whole word, which needs the section's
      whole vocabulary rather than any one word.

    Both are marked derived so indexing recomputes them instead of carrying them
    forward, exactly as it does for `TESTS`.
    """
    edges: list[RelationRecord] = []
    seen: set[tuple[str, str]] = set()

    for reference in routes:
        source = index.symbols_by_id.get(reference.source_symbol_id)
        if source is None or source.kind is not SymbolKind.DOCUMENT_SECTION:
            continue
        for owner in route_index.owners.get(reference.target_hint, ()):
            if owner.file_id == reference.file_id:
                continue
            key = (source.symbol_id, owner.symbol_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                _derived_edge(
                    source_symbol_id=source.symbol_id,
                    target=owner,
                    file_id=reference.file_id,
                    target_hint=reference.target_hint,
                    start_line=reference.start_line,
                    end_line=reference.end_line,
                )
            )

    edges.extend(_derive_config_edges(mentions, index, seen))
    return edges


def _derive_config_edges(
    mentions: Sequence[SymbolReference],
    index: _Index,
    seen: set[tuple[str, str]],
) -> list[RelationRecord]:
    """Link a section to a configuration key it spells out segment by segment.

    Requiring *every* segment is what keeps this quiet. A section mentioning
    "port" alone matches nothing; one mentioning both "service" and "port"
    matches ``service.port`` and no other key. A single-segment key is never
    matched, because a bare top-level name is an ordinary word.
    """
    words_by_section: dict[str, dict[str, tuple[str, int]]] = {}
    for reference in mentions:
        bucket = words_by_section.setdefault(reference.source_symbol_id, {})
        bucket.setdefault(
            reference.target_hint.lower(), (reference.file_id, reference.start_line)
        )

    edges: list[RelationRecord] = []
    for section_id, words in words_by_section.items():
        section = index.symbols_by_id.get(section_id)
        if section is None or section.kind is not SymbolKind.DOCUMENT_SECTION:
            continue
        for symbol in index.symbols_by_id.values():
            if symbol.kind is not SymbolKind.CONFIG_KEY:
                continue
            for path in _dotted_paths(symbol):
                segments = path.lower().split(".")
                if len(segments) < 2 or any(part not in words for part in segments):
                    continue
                key = (section_id, symbol.symbol_id)
                if key in seen:
                    continue
                seen.add(key)
                file_id, line = min(words[part] for part in segments)
                edges.append(
                    _derived_edge(
                        source_symbol_id=section_id,
                        target=symbol,
                        file_id=file_id,
                        target_hint=path,
                        start_line=line,
                        end_line=line,
                    )
                )
                break
    edges.sort(key=lambda item: item.relation_id)
    return edges


def _dotted_paths(symbol: SymbolRecord) -> tuple[str, ...]:
    """The nested key paths a configuration symbol summarizes."""
    return tuple(
        part.strip() for part in symbol.module_path.split(",") if part.strip()
    )


def _derived_edge(
    *,
    source_symbol_id: str,
    target: SymbolRecord,
    file_id: str,
    target_hint: str,
    start_line: int,
    end_line: int,
) -> RelationRecord:
    """Build one derived `DOCUMENTS` edge.

    The target's ID joins the relation ID because one reference may produce
    several of these, and two edges from the same line would otherwise collide
    on the primary key.
    """
    return RelationRecord(
        relation_id=build_relation_id(
            source_symbol_id,
            RelationKind.DOCUMENTS.value,
            f"{target_hint}#{target.symbol_id}",
            start_line,
        ),
        source_symbol_id=source_symbol_id,
        target_symbol_id=target.symbol_id,
        file_id=file_id,
        kind=RelationKind.DOCUMENTS,
        target_hint=target_hint,
        resolution=ResolutionState.RESOLVED,
        derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        confidence=_CONFIDENCE[Derivation.LOW_CONFIDENCE_HEURISTIC],
        start_line=start_line,
        end_line=end_line,
        candidate_count=1,
        module_hint=DERIVED_HINT,
    )


def _derive_test_edges(
    relations: Sequence[RelationRecord], index: _Index
) -> list[RelationRecord]:
    """Emit `TESTS` where a test symbol both imports and calls a target.

    Both conditions are required. A test that merely mentions a name is not
    evidence that it tests it, and a file that imports something it never
    exercises has not tested it either.
    """
    imported_by_file: dict[str, set[str]] = {}
    for relation in relations:
        if (
            relation.kind is RelationKind.IMPORTS
            and relation.target_symbol_id is not None
        ):
            imported_by_file.setdefault(relation.file_id, set()).add(
                relation.target_symbol_id
            )

    edges: list[RelationRecord] = []
    seen: set[tuple[str, str]] = set()
    for relation in relations:
        if relation.kind is not RelationKind.CALLS:
            continue
        target = relation.target_symbol_id
        if target is None:
            continue
        source_file = index.files_by_id.get(relation.file_id)
        if (
            source_file is None
            or source_file.classification is not FileClassification.TEST_CODE
        ):
            continue
        if target not in imported_by_file.get(relation.file_id, set()):
            continue
        key = (relation.source_symbol_id, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            RelationRecord(
                relation_id=build_relation_id(
                    relation.source_symbol_id,
                    RelationKind.TESTS.value,
                    relation.target_hint,
                    relation.start_line,
                ),
                source_symbol_id=relation.source_symbol_id,
                target_symbol_id=target,
                file_id=relation.file_id,
                kind=RelationKind.TESTS,
                target_hint=relation.target_hint,
                resolution=ResolutionState.RESOLVED,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=_CONFIDENCE[Derivation.HIGH_CONFIDENCE_HEURISTIC],
                start_line=relation.start_line,
                end_line=relation.end_line,
                candidate_count=1,
            )
        )
    return edges


def _conftest_scope(index: _Index) -> dict[str, list[str]]:
    """Directory prefix -> file IDs of `conftest.py` files at that prefix.

    Keys are the containing directory of each conftest, normalized to use "/"
    and to be "" at the repository root.
    """
    scope: dict[str, list[str]] = {}
    for record in index.files_by_id.values():
        path = record.relative_path.replace("\\", "/")
        if path.rsplit("/", 1)[-1] != "conftest.py":
            continue
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        scope.setdefault(directory, []).append(record.file_id)
    for file_ids in scope.values():
        file_ids.sort()
    return scope


def _visible_fixture(
    name: str, test_file_id: str, index: _Index, conftests: dict[str, list[str]]
) -> SymbolRecord | None:
    """The fixture `name` refers to, searched own file then ancestor conftests.

    Scoping is deliberately partial: pytest also resolves fixtures through
    plugins, `usefixtures`, and dynamic registration, none of which are visible
    to static analysis. Partial scoping over-matches rather than under-matches,
    and over-matching at a derivation that cannot close a test gap is the safe
    direction to be wrong in.
    """
    own = index.name_in_file.get((test_file_id, name), ())
    for symbol in own:
        if symbol.kind is SymbolKind.FIXTURE:
            return symbol

    record = index.files_by_id.get(test_file_id)
    if record is None:
        return None
    path = record.relative_path.replace("\\", "/")
    directory = path.rsplit("/", 1)[0] if "/" in path else ""

    # Nearest ancestor wins, so walk from the test's own directory upward.
    while True:
        for file_id in conftests.get(directory, ()):
            for symbol in index.name_in_file.get((file_id, name), ()):
                if symbol.kind is SymbolKind.FIXTURE:
                    return symbol
        if directory == "":
            return None
        directory = directory.rsplit("/", 1)[0] if "/" in directory else ""


def _derive_fixture_test_edges(
    relations: Sequence[RelationRecord], index: _Index
) -> list[RelationRecord]:
    """Emit `TESTS` where a test consumes a fixture that reaches the target.

    The edge is `low_confidence_heuristic`: a fixture constructing an object is
    evidence that the test exercises it, but the test never names the target,
    so the link is inference rather than a statement the source makes.
    """
    existing = {
        (relation.source_symbol_id, relation.target_symbol_id)
        for relation in relations
        if relation.kind is RelationKind.TESTS
    }
    calls_by_source: dict[str, list[RelationRecord]] = {}
    for relation in relations:
        if (
            relation.kind is RelationKind.CALLS
            and relation.target_symbol_id is not None
        ):
            calls_by_source.setdefault(relation.source_symbol_id, []).append(relation)

    conftests = _conftest_scope(index)
    edges: list[RelationRecord] = []
    seen: set[tuple[str, str]] = set()
    for relation in relations:
        if relation.kind is not RelationKind.CONSUMES_FIXTURE:
            continue
        fixture = _visible_fixture(
            relation.target_hint, relation.file_id, index, conftests
        )
        if fixture is None:
            continue
        for call in calls_by_source.get(fixture.symbol_id, ()):
            target = call.target_symbol_id
            if target is None:
                continue
            target_file = index.files_by_id.get(index.file_of_symbol.get(target, ""))
            if (
                target_file is None
                or target_file.classification is FileClassification.TEST_CODE
            ):
                continue
            key = (relation.source_symbol_id, target)
            # A strict import-and-call edge already states this more strongly.
            if key in existing or key in seen:
                continue
            seen.add(key)
            edges.append(
                RelationRecord(
                    relation_id=build_relation_id(
                        relation.source_symbol_id,
                        RelationKind.TESTS.value,
                        f"fixture:{relation.target_hint}:{call.target_hint}",
                        relation.start_line,
                    ),
                    source_symbol_id=relation.source_symbol_id,
                    target_symbol_id=target,
                    file_id=relation.file_id,
                    kind=RelationKind.TESTS,
                    target_hint=call.target_hint,
                    resolution=ResolutionState.RESOLVED,
                    derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                    confidence=_CONFIDENCE[Derivation.LOW_CONFIDENCE_HEURISTIC],
                    start_line=relation.start_line,
                    end_line=relation.end_line,
                    candidate_count=1,
                    # How this edge was derived, so a gap reason can name it
                    # without re-deriving. `_derive_document_edges` already uses
                    # `module_hint` this way (`DERIVED_HINT`).
                    module_hint=FIXTURE_HINT,
                )
            )
    return edges


def _derive_helper_test_edges(
    relations: Sequence[RelationRecord], index: _Index
) -> list[RelationRecord]:
    """Emit `TESTS` where a test calls a test helper that calls the target.

    Exactly one intermediate hop. Two hops through shared test utilities would
    reach a large fraction of any codebase, which makes the signal worthless
    rather than merely weak.
    """
    existing = {
        (relation.source_symbol_id, relation.target_symbol_id)
        for relation in relations
        if relation.kind is RelationKind.TESTS
    }
    calls_by_source: dict[str, list[RelationRecord]] = {}
    for relation in relations:
        if (
            relation.kind is RelationKind.CALLS
            and relation.target_symbol_id is not None
        ):
            calls_by_source.setdefault(relation.source_symbol_id, []).append(relation)

    def in_test_code(symbol_id: str) -> bool:
        record = index.files_by_id.get(index.file_of_symbol.get(symbol_id, ""))
        return (
            record is not None
            and record.classification is FileClassification.TEST_CODE
        )

    edges: list[RelationRecord] = []
    seen: set[tuple[str, str]] = set()
    for symbol in index.symbols_by_id.values():
        if symbol.kind is not SymbolKind.TEST:
            continue
        for first in calls_by_source.get(symbol.symbol_id, ()):
            helper_id = first.target_symbol_id
            if helper_id is None or not in_test_code(helper_id):
                continue
            for second in calls_by_source.get(helper_id, ()):
                target = second.target_symbol_id
                if target is None or in_test_code(target):
                    continue
                key = (symbol.symbol_id, target)
                if key in existing or key in seen:
                    continue
                seen.add(key)
                edges.append(
                    RelationRecord(
                        relation_id=build_relation_id(
                            symbol.symbol_id,
                            RelationKind.TESTS.value,
                            f"helper:{first.target_hint}:{second.target_hint}",
                            first.start_line,
                        ),
                        source_symbol_id=symbol.symbol_id,
                        target_symbol_id=target,
                        file_id=first.file_id,
                        kind=RelationKind.TESTS,
                        target_hint=second.target_hint,
                        resolution=ResolutionState.RESOLVED,
                        derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                        confidence=_CONFIDENCE[Derivation.LOW_CONFIDENCE_HEURISTIC],
                        start_line=first.start_line,
                        end_line=first.end_line,
                        candidate_count=1,
                        module_hint=HELPER_HINT,
                    )
                )
    return edges


def _build(
    reference: SymbolReference,
    *,
    target: SymbolRecord | None,
    resolution: ResolutionState,
    derivation: Derivation,
    candidate_count: int,
    kind: RelationKind | None = None,
) -> RelationRecord:
    effective_kind = kind or reference.kind
    return RelationRecord(
        relation_id=build_relation_id(
            reference.source_symbol_id,
            effective_kind.value,
            reference.target_hint,
            reference.start_line,
            reference.part,
        ),
        source_symbol_id=reference.source_symbol_id,
        target_symbol_id=target.symbol_id if target is not None else None,
        file_id=reference.file_id,
        kind=effective_kind,
        target_hint=reference.target_hint,
        resolution=resolution,
        derivation=derivation,
        confidence=_CONFIDENCE[derivation],
        start_line=reference.start_line,
        end_line=reference.end_line,
        candidate_count=candidate_count,
        # Carried so the relation round-trips back into its reference on the
        # next run. Dropping either one silently loses an edge: `module_hint`
        # is what resolves an import, and `reference_part` is the only thing
        # separating two otherwise identical references on one line.
        module_hint=reference.module_hint,
        reference_part=reference.part,
    )


def _resolve_module(
    specifier: str, source: FileRecord, index: _Index
) -> str | None:
    """Map a module specifier onto a repository file, or ``None`` if external.

    Comparison is case-sensitive on normalized relative paths. A case-only
    mismatch therefore stays unresolved even on Windows, where the filesystem
    would happily open the file: silently matching would make the same
    repository resolve differently on different platforms.
    """
    if not specifier:
        return None

    if specifier.startswith("."):
        if specifier.startswith(("./", "../")):
            return _resolve_relative_path(specifier, source, index)
        return _resolve_python_relative(specifier, source, index)

    direct = index.module_to_file.get(specifier)
    if direct is not None:
        return direct

    # A dotted Python module may sit under a source root such as `src/`.
    for module_path, file_id in index.module_to_file.items():
        if module_path == specifier or module_path.endswith(f".{specifier}"):
            return file_id
    return None


def _resolve_python_relative(
    specifier: str, source: FileRecord, index: _Index
) -> str | None:
    level = len(specifier) - len(specifier.lstrip("."))
    remainder = specifier[level:]
    package = _python_module(source.relative_path).split(".")
    # One dot means "this package", so the module's own name is dropped first.
    ascend = level
    base = package[: max(len(package) - ascend, 0)]
    parts = [*base, *(remainder.split(".") if remainder else [])]
    return index.module_to_file.get(".".join(parts))


def _resolve_relative_path(
    specifier: str, source: FileRecord, index: _Index
) -> str | None:
    directory = _directory(source.relative_path)
    segments = [segment for segment in directory.split("/") if segment]
    for part in specifier.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if segments:
                segments.pop()
            continue
        segments.append(part)

    target = "/".join(segments)
    found = index.path_stem_to_file.get(target)
    if found is not None:
        return found
    for extension in _TSJS_EXTENSIONS:
        found = index.path_stem_to_file.get(f"{target}{extension}")
        if found is not None:
            return found
    return index.path_stem_to_file.get(f"{target}/index")


def _python_module(relative_path: str) -> str:
    without_suffix = relative_path.rsplit(".", 1)[0]
    dotted = without_suffix.replace("/", ".")
    if dotted.endswith(".__init__"):
        return dotted[: -len(".__init__")]
    return dotted


def _path_stem(relative_path: str) -> str:
    name = relative_path.rsplit("/", 1)[-1]
    if "." not in name:
        return relative_path
    return relative_path[: -(len(name) - name.rfind("."))]


def _directory(relative_path: str) -> str:
    return relative_path.rsplit("/", 1)[0] if "/" in relative_path else ""
