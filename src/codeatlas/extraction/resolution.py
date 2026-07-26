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

from codeatlas.contracts import Derivation, RelationKind
from codeatlas.domain.ids import relation_id as build_relation_id
from codeatlas.domain.relations import RelationRecord, ResolutionState, SymbolReference
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord

RESOLVER_VERSION: str = "1.0.0"

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

        for reference in references:
            if reference.kind is RelationKind.IMPORTS:
                continue
            relations.append(_resolve_reference(reference, index, imports_by_file))

        relations.extend(_derive_test_edges(relations, index))
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
