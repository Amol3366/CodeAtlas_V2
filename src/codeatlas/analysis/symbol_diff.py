"""Symbol-level diff between two states.

Symbols are matched by ``(kind, qualified_name)``, and occurrences sharing a
file are paired before anything cross-file is considered (ADR-0042): a key name
common to several config files is not ambiguous within any one of them. A unique
cross-file match that survives that pairing is a move; a non-unique match is left
as delete plus add so the engine never emits an ungrounded move.
Content-unchanged symbols are still reported when their resolved edge set differs.

One edit is one change. A member's text lives inside its container's range, so
every member edit also moves the container's hash; reporting both would
double-count the edit. The folding rules (:func:`_fold_nested_changes`) state
which of the two speaks: a *code* container (a class) is reported through its
changed members, a *type* container (interface, type alias, enum) absorbs its
members because a field is the type's shape, and a deleted or added container
carries its whole subtree.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from codeatlas.contracts import ChangeKind, RelationKind, SymbolKind
from codeatlas.domain.change import SignatureChangeClass, SymbolChange
from codeatlas.domain.relations import MENTION_HINT, ROUTE_HINT, RelationRecord
from codeatlas.domain.symbols import SymbolRecord

# Containers reported through their members rather than in their own right.
# A class qualifies because a method's text lives inside it; a configuration
# key qualifies because a mapping key's value *is* its subtree, so editing one
# leaf moves the hash of every ancestor above it (ADR-0042).
_CODE_CONTAINER_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.CLASS, SymbolKind.CONFIG_KEY}
)

# Containers whose members are shape: they absorb their members' changes.
_TYPE_CONTAINER_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.INTERFACE, SymbolKind.TYPE_ALIAS, SymbolKind.ENUM}
)

# Change kinds that prove the container's text differs somewhere inside.
_CONTENT_CHANGE_KINDS: Final[frozenset[ChangeKind]] = frozenset(
    {
        ChangeKind.ADDED,
        ChangeKind.DELETED,
        ChangeKind.MODIFIED,
        ChangeKind.MOVED,
    }
)


@dataclass(frozen=True)
class SymbolDiffInput:
    """Everything needed to diff one side's symbols."""

    symbols: Sequence[SymbolRecord]
    relations: Sequence[RelationRecord]
    file_paths: dict[str, str]


def compute_symbol_changes(
    base: SymbolDiffInput,
    target: SymbolDiffInput,
) -> tuple[SymbolChange, ...]:
    """Return symbol-level changes between two states.

    ``MODULE`` symbols are excluded from the changed-symbol list; their changes
    surface through their members and dependency findings.
    """
    base_by_key = _group_by_key(base.symbols)
    target_by_key = _group_by_key(target.symbols)
    all_keys = set(base_by_key) | set(target_by_key)

    # Names present on exactly one side. A surviving symbol whose edge to one
    # of these re-resolves is *impacted* by the lifecycle event, not changed:
    # the impact engine reports it as an unresolved dependent.
    lifecycle_names = {name for _, name in set(base_by_key) ^ set(target_by_key)}
    context = _DependencyContext(
        base_names={s.symbol_id: s.qualified_name for s in base.symbols},
        target_names={s.symbol_id: s.qualified_name for s in target.symbols},
        lifecycle_names=lifecycle_names,
        base_bindings=_import_bindings(base.relations),
        target_bindings=_import_bindings(target.relations),
        base_by_source=_group_by_source(base.relations),
        target_by_source=_group_by_source(target.relations),
        target_binding_lines=_import_binding_lines(target.relations),
    )

    changes: list[SymbolChange] = []
    limitations: list[str] = []

    for key in sorted(all_keys):
        base_symbols = base_by_key.get(key, ())
        target_symbols = target_by_key.get(key, ())
        changes.extend(
            _classify_key(
                key,
                base_symbols,
                target_symbols,
                base,
                target,
                limitations,
                context,
            )
        )

    return _fold_nested_changes(changes)


def _group_by_key(
    symbols: Sequence[SymbolRecord],
) -> dict[tuple[SymbolKind, str], tuple[SymbolRecord, ...]]:
    groups: dict[tuple[SymbolKind, str], list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        if symbol.kind is SymbolKind.MODULE:
            continue
        groups[(symbol.kind, symbol.qualified_name)].append(symbol)
    return {
        key: tuple(sorted(items, key=lambda s: (s.file_id, s.start_line)))
        for key, items in groups.items()
    }


@dataclass(frozen=True)
class _DependencyContext:
    """What dependency detection needs to tell change from impact."""

    base_names: dict[str, str]
    target_names: dict[str, str]
    lifecycle_names: set[str]
    base_bindings: dict[tuple[str, str], str]
    target_bindings: dict[tuple[str, str], str]
    # Relations indexed by the symbol they leave, grouped once per analysis.
    #
    # `_dependency_changed` and `_binding_span` need one symbol's outgoing
    # edges, and both used to find them by filtering the whole list. Both run
    # once per surviving symbol pair, so the cost was O(symbols x relations) --
    # a measured log-log exponent of 2.02 while every other engine stage sat at
    # ~1.0. Grouping here is the same move `_group_by_key` already makes for
    # symbols, and it makes the lookup O(1).
    base_by_source: dict[str, tuple[RelationRecord, ...]] = field(
        default_factory=dict
    )
    target_by_source: dict[str, tuple[RelationRecord, ...]] = field(
        default_factory=dict
    )
    target_binding_lines: dict[tuple[str, str], int] = field(default_factory=dict)


def _group_by_source(
    relations: Sequence[RelationRecord],
) -> dict[str, tuple[RelationRecord, ...]]:
    """Index relations by the symbol they leave, preserving their order.

    Order is preserved because `_binding_span` takes a min and max over the
    lines it collects; a reordering could not change that result, but relying
    on it would be an accident rather than a decision.
    """
    grouped: dict[str, list[RelationRecord]] = {}
    for relation in relations:
        grouped.setdefault(relation.source_symbol_id, []).append(relation)
    return {source: tuple(items) for source, items in grouped.items()}


def _import_bindings(
    relations: Sequence[RelationRecord],
) -> dict[tuple[str, str], str]:
    """Which module each name is imported from, per file.

    The binding lives on the ``MODULE`` symbol, which the diff excludes, so it
    must be carried onto the referencing symbols' edges: a call that resolves
    through an explicit import and the same call resolving by name search are
    different statements about the dependency (c011).
    """
    return {
        (relation.file_id, relation.target_hint): relation.module_hint or "<import>"
        for relation in relations
        if relation.kind is RelationKind.IMPORTS and not relation.is_derived
    }


def _import_binding_lines(
    relations: Sequence[RelationRecord],
) -> dict[tuple[str, str], int]:
    """Where each import binding is written, for citation only.

    Kept apart from :func:`_import_bindings` on purpose: an import that merely
    moved to another line is not a dependency change, so the line may never
    participate in the edge comparison.
    """
    return {
        (relation.file_id, relation.target_hint): relation.start_line
        for relation in relations
        if relation.kind is RelationKind.IMPORTS and not relation.is_derived
    }


def _classify_key(
    key: tuple[SymbolKind, str],
    base_symbols: tuple[SymbolRecord, ...],
    target_symbols: tuple[SymbolRecord, ...],
    base: SymbolDiffInput,
    target: SymbolDiffInput,
    limitations: list[str],
    context: _DependencyContext,
) -> tuple[SymbolChange, ...]:
    _kind, qualified_name = key

    if len(base_symbols) == 1 and len(target_symbols) == 1:
        return _classify_one_to_one(
            key,
            base_symbols[0],
            target_symbols[0],
            base,
            target,
            context,
        )

    if len(base_symbols) == 0:
        return tuple(_added(symbol, target.file_paths) for symbol in target_symbols)

    if len(target_symbols) == 0:
        return tuple(_deleted(symbol, base.file_paths) for symbol in base_symbols)

    # A name shared by several files is not ambiguous within any one of them.
    # Pairing same-file occurrences first is what stops `cases` in five config
    # files from being a five-versus-five match: that fell straight to the
    # ambiguous branch below and reported all ten as delete plus add, on
    # byte-identical content, for a repository nobody had edited.
    paired, base_symbols, target_symbols = _pair_within_files(
        key, base_symbols, target_symbols, base, target, context
    )
    if not base_symbols and not target_symbols:
        return paired
    if not base_symbols:
        return paired + tuple(
            _added(symbol, target.file_paths) for symbol in target_symbols
        )
    if not target_symbols:
        return paired + tuple(
            _deleted(symbol, base.file_paths) for symbol in base_symbols
        )
    # What is left after same-file pairing can still be a move: exactly one
    # occurrence on each side, in different files, is the unique cross-file
    # match this module has always carried across.
    if len(base_symbols) == 1 and len(target_symbols) == 1:
        return paired + _classify_one_to_one(
            key,
            base_symbols[0],
            target_symbols[0],
            base,
            target,
            context,
        )

    # Non-unique match: report every base symbol as deleted and every target
    # symbol as added, with a single limitation explaining the ambiguity.
    limitations.append(
        f"AMBIGUOUS_SYMBOL_MATCH: {qualified_name} has {len(base_symbols)} "
        f"base occurrence(s) and {len(target_symbols)} target occurrence(s); "
        "reported as delete plus add rather than a move."
    )
    deleted = tuple(_deleted(symbol, base.file_paths) for symbol in base_symbols)
    added = tuple(_added(symbol, target.file_paths) for symbol in target_symbols)
    return deleted + added


def _pair_within_files(
    key: tuple[SymbolKind, str],
    base_symbols: tuple[SymbolRecord, ...],
    target_symbols: tuple[SymbolRecord, ...],
    base: SymbolDiffInput,
    target: SymbolDiffInput,
    context: _DependencyContext,
) -> tuple[
    tuple[SymbolChange, ...], tuple[SymbolRecord, ...], tuple[SymbolRecord, ...]
]:
    """Match occurrences that share a file, and return what is left over.

    Occurrences pair by ``symbol_id`` first, then -- on whatever is left -- by
    being the only candidate on each side.

    **This used to pair only files holding exactly one occurrence per side**,
    on the grounds that two occurrences of one name in a file are ambiguous and
    guessing between them is the ungrounded move this module refuses to make.
    That reasoning was correct until ADR-0069 and outlived it: those
    occurrences used to *share* an id, so there was nothing to pair on. They no
    longer do.

    Leaving it produced a serious defect in the core wedge, found 2026-09-04 by
    running preflight on five unmodified real repositories. Every ``git
    status`` was empty; gson, cobra, gin and scalaz **failed outright** (the
    report contract rejects an empty ``changed_files`` beside a non-empty
    ``changed_symbols``), and ripgrep reported **102 changed symbols and 51
    findings at high risk** -- exactly 51 x 2, 51 being the total membership of
    its 17 ordinal-carried collision groups.

    Pairing by file *path*, not file id: a **file** id is not stable across the
    two state views. A **symbol** id is, which is the distinction that makes
    this work -- measured rather than assumed.
    """
    base_by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in base_symbols:
        base_by_path[base.file_paths.get(symbol.file_id, symbol.file_id)].append(symbol)
    target_by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in target_symbols:
        target_by_path[
            target.file_paths.get(symbol.file_id, symbol.file_id)
        ].append(symbol)

    paired: list[SymbolChange] = []
    matched: set[int] = set()
    for path in sorted(set(base_by_path) & set(target_by_path)):
        mine, theirs = base_by_path[path], target_by_path[path]

        # Pair by `symbol_id` first, which is what makes more than one
        # occurrence tractable at all.
        #
        # Before ADR-0069 every occurrence of a name in a file collapsed onto
        # ONE id, so there was nothing to pair on and refusing to guess was
        # right. ADR-0069 gives each a distinct, deterministic id, and the two
        # state views compute the same id from the same bytes -- measured on
        # gson: 4,414 symbols per side, 4,414 ids in common, none on either
        # side alone, and all 99 of its colliding groups matching across both
        # views. So this is the identity the parser already assigned, not a
        # choice between look-alikes.
        by_id = {symbol.symbol_id: symbol for symbol in theirs}
        for base_symbol in mine:
            target_symbol = by_id.get(base_symbol.symbol_id)
            if target_symbol is None:
                continue
            paired.extend(
                _classify_one_to_one(
                    key, base_symbol, target_symbol, base, target, context
                )
            )
            matched.add(id(base_symbol))
            matched.add(id(target_symbol))

        # Then the original rule, on whatever the ids did not claim. Kept
        # rather than replaced: a lone occurrence whose id moved for some other
        # reason still pairs by being the only candidate, exactly as before.
        mine = [symbol for symbol in mine if id(symbol) not in matched]
        theirs = [symbol for symbol in theirs if id(symbol) not in matched]
        if len(mine) != 1 or len(theirs) != 1:
            continue
        paired.extend(
            _classify_one_to_one(key, mine[0], theirs[0], base, target, context)
        )
        matched.add(id(mine[0]))
        matched.add(id(theirs[0]))

    return (
        tuple(paired),
        tuple(s for s in base_symbols if id(s) not in matched),
        tuple(s for s in target_symbols if id(s) not in matched),
    )


def _classify_one_to_one(
    key: tuple[SymbolKind, str],
    base_symbol: SymbolRecord,
    target_symbol: SymbolRecord,
    base: SymbolDiffInput,
    target: SymbolDiffInput,
    context: _DependencyContext,
) -> tuple[SymbolChange, ...]:
    base_path = base.file_paths.get(base_symbol.file_id)
    target_path = target.file_paths.get(target_symbol.file_id)

    if base_symbol.file_id == target_symbol.file_id:
        if base_symbol.content_hash == target_symbol.content_hash:
            if _dependency_changed(base_symbol, target_symbol, context):
                return (
                    _dependency(
                        key,
                        base_symbol,
                        target_symbol,
                        base_path,
                        target_path,
                        span=_binding_span(base_symbol, target_symbol, context),
                    ),
                )
            return ()
        return (
            _modified(
                key,
                base_symbol,
                target_symbol,
                base_path,
                target_path,
            ),
        )

    return (
        _moved(
            key,
            base_symbol,
            target_symbol,
            base_path,
            target_path,
        ),
    )


def _added(symbol: SymbolRecord, file_paths: dict[str, str]) -> SymbolChange:
    path = file_paths.get(symbol.file_id)
    return SymbolChange(
        qualified_name=symbol.qualified_name,
        symbol_kind=symbol.kind,
        change_kind=ChangeKind.ADDED,
        file_path=path or symbol.file_id,
        target_start_line=symbol.start_line,
        target_end_line=symbol.end_line,
        public=symbol.visibility == "public",
    )


def _deleted(symbol: SymbolRecord, file_paths: dict[str, str]) -> SymbolChange:
    path = file_paths.get(symbol.file_id)
    return SymbolChange(
        qualified_name=symbol.qualified_name,
        symbol_kind=symbol.kind,
        change_kind=ChangeKind.DELETED,
        file_path=path or symbol.file_id,
        base_file_path=path or symbol.file_id,
        base_start_line=symbol.start_line,
        base_end_line=symbol.end_line,
        public=symbol.visibility == "public",
    )


def _modified(
    key: tuple[SymbolKind, str],
    base_symbol: SymbolRecord,
    target_symbol: SymbolRecord,
    base_path: str | None,
    target_path: str | None,
) -> SymbolChange:
    _, qualified_name = key
    return SymbolChange(
        qualified_name=qualified_name,
        symbol_kind=target_symbol.kind,
        change_kind=ChangeKind.MODIFIED,
        file_path=target_path or target_symbol.file_id,
        base_file_path=base_path if base_path != target_path else None,
        base_start_line=base_symbol.start_line,
        base_end_line=base_symbol.end_line,
        target_start_line=target_symbol.start_line,
        target_end_line=target_symbol.end_line,
        signature_change_class=_signature_change_class(
            base_symbol.signature,
            target_symbol.signature,
        ),
        public=target_symbol.visibility == "public",
    )


def _moved(
    key: tuple[SymbolKind, str],
    base_symbol: SymbolRecord,
    target_symbol: SymbolRecord,
    base_path: str | None,
    target_path: str | None,
) -> SymbolChange:
    _, qualified_name = key
    return SymbolChange(
        qualified_name=qualified_name,
        symbol_kind=target_symbol.kind,
        change_kind=ChangeKind.MOVED,
        file_path=target_path or target_symbol.file_id,
        base_file_path=base_path or base_symbol.file_id,
        base_start_line=base_symbol.start_line,
        base_end_line=base_symbol.end_line,
        target_start_line=target_symbol.start_line,
        target_end_line=target_symbol.end_line,
        signature_change_class=_signature_change_class(
            base_symbol.signature,
            target_symbol.signature,
        ),
        public=target_symbol.visibility == "public",
    )


def _dependency(
    key: tuple[SymbolKind, str],
    base_symbol: SymbolRecord,
    target_symbol: SymbolRecord,
    base_path: str | None,
    target_path: str | None,
    span: tuple[int, int] | None = None,
) -> SymbolChange:
    _, qualified_name = key
    return SymbolChange(
        qualified_name=qualified_name,
        symbol_kind=target_symbol.kind,
        change_kind=ChangeKind.DEPENDENCY,
        file_path=target_path or target_symbol.file_id,
        base_file_path=base_path if base_path != target_path else None,
        base_start_line=base_symbol.start_line,
        base_end_line=base_symbol.end_line,
        target_start_line=target_symbol.start_line,
        target_end_line=target_symbol.end_line,
        public=target_symbol.visibility == "public",
        evidence_start_line=span[0] if span else None,
        evidence_end_line=span[1] if span else None,
    )


def _binding_span(
    base_symbol: SymbolRecord,
    target_symbol: SymbolRecord,
    context: _DependencyContext,
) -> tuple[int, int] | None:
    """The citation for a binding-driven dependency change.

    Runs from the import statement to the reference that resolves through it
    (c011: the added import through the call it now binds). When the change was
    not binding-driven — a resolution flip with no import involved — there is
    no single span that proves it, and the whole symbol speaks instead.
    """
    lines: list[int] = []
    for relation in context.target_by_source.get(target_symbol.symbol_id, ()):
        key = (relation.file_id, relation.target_hint)
        if context.base_bindings.get(
            (base_symbol.file_id, relation.target_hint)
        ) == context.target_bindings.get(key):
            continue
        lines.append(relation.start_line)
        binding_line = context.target_binding_lines.get(key)
        if binding_line is not None:
            lines.append(binding_line)
    if not lines:
        return None
    return (min(lines), max(lines))


def _dependency_changed(
    base_symbol: SymbolRecord,
    target_symbol: SymbolRecord,
    context: _DependencyContext,
) -> bool:
    """Whether this symbol's stated references resolve differently.

    Only deterministically-stated references count. A route or mention edge is
    a heuristic that may re-resolve when *other* files change, and an edge
    whose referent was itself added or deleted re-resolves because of the
    referent's lifecycle — both are impact on this symbol, never a change of
    it.
    """

    def considered(relation: RelationRecord, names: dict[str, str]) -> bool:
        if relation.kind is RelationKind.TESTS:
            return False
        if relation.is_derived:
            return False
        if relation.module_hint in (ROUTE_HINT, MENTION_HINT):
            return False
        referent = relation.target_hint
        if relation.target_symbol_id is not None:
            referent = names.get(relation.target_symbol_id, referent)
        return referent not in context.lifecycle_names

    def edge_key(
        relation: RelationRecord, bindings: dict[tuple[str, str], str]
    ) -> tuple[str, str, str | None, str, str | None]:
        return (
            relation.kind.value,
            relation.target_hint,
            relation.target_symbol_id,
            relation.resolution.value,
            # The import binding the reference resolves through. Same target,
            # different binding is still a dependency change (c011).
            bindings.get((relation.file_id, relation.target_hint)),
        )

    base_edges = {
        edge_key(relation, context.base_bindings)
        for relation in context.base_by_source.get(base_symbol.symbol_id, ())
        if considered(relation, context.base_names)
    }
    target_edges = {
        edge_key(relation, context.target_bindings)
        for relation in context.target_by_source.get(target_symbol.symbol_id, ())
        if considered(relation, context.target_names)
    }
    return base_edges != target_edges


def _fold_nested_changes(
    changes: Sequence[SymbolChange],
) -> tuple[SymbolChange, ...]:
    """Collapse container/member double counting: one edit, one change.

    Three rules, each stated where the corpus draws the line:

    1. A deleted or added container carries its subtree (c006): the members'
       lifecycle is the container's, and one fact is reported once.
    2. A *type* container absorbs its modified members (c007): a field is the
       type's shape, so the type is the changed contract.
    3. A *code* container (class) whose own signature is unchanged is reported
       through its changed members (c001-c004): its hash moved only because a
       member's text lives inside its range.

    Limitation, stated rather than hidden: rule 3 folds a class-level
    statement change away when it lands in the same comparison as a member
    change, because content hashes cannot separate the two without re-reading
    both bodies. A class-level change alone still reports the class.
    """
    kept = list(changes)

    def lifecycle_member(change: SymbolChange) -> bool:
        if change.change_kind not in (ChangeKind.ADDED, ChangeKind.DELETED):
            return False
        side = "target" if change.change_kind is ChangeKind.ADDED else "base"
        return any(
            other is not change
            and other.change_kind is change.change_kind
            and _contains_on(side, other, change)
            for other in kept
        )

    kept = [change for change in kept if not lifecycle_member(change)]

    def folded_type_member(change: SymbolChange) -> bool:
        if change.change_kind is not ChangeKind.MODIFIED:
            return False
        return any(
            other is not change
            and other.change_kind is ChangeKind.MODIFIED
            and other.symbol_kind in _TYPE_CONTAINER_KINDS
            and _contains_on("target", other, change)
            for other in kept
        )

    kept = [change for change in kept if not folded_type_member(change)]

    def shadowed_container(change: SymbolChange) -> bool:
        if change.symbol_kind not in _CODE_CONTAINER_KINDS:
            return False
        if change.change_kind is not ChangeKind.MODIFIED:
            return False
        if change.signature_change_class is not SignatureChangeClass.NONE:
            return False
        return any(
            other is not change
            and other.change_kind in _CONTENT_CHANGE_KINDS
            and (
                _contains_on("target", change, other)
                or _contains_on("base", change, other)
                or _encloses_key(change, other)
            )
            for other in kept
        )

    kept = [change for change in kept if not shadowed_container(change)]
    return tuple(kept)


def _encloses_key(outer: SymbolChange, inner: SymbolChange) -> bool:
    """Whether one configuration key contains another, by dotted path.

    Line ranges cannot answer this. ADR-0041 gave every nested key its own
    line, so `service.api` and `service.api.http` are single-line ranges that do
    not contain the leaf below them -- only the top-level key still spans its
    block. The dotted path states the nesting exactly and does not depend on
    that line heuristic succeeding.

    The trailing dot is the whole point: `service.apikey` is a sibling of
    `service.api`, not a child of it.
    """
    if (
        outer.symbol_kind is not SymbolKind.CONFIG_KEY
        or inner.symbol_kind is not SymbolKind.CONFIG_KEY
    ):
        return False
    if outer.file_path != inner.file_path:
        return False
    return inner.qualified_name.startswith(f"{outer.qualified_name}.")


def _contains_on(
    side: str, outer: SymbolChange, inner: SymbolChange
) -> bool:
    """Whether ``outer``'s range strictly contains ``inner``'s on one side."""
    outer_span = _side_span(outer, side)
    inner_span = _side_span(inner, side)
    if outer_span is None or inner_span is None:
        return False
    outer_path, outer_start, outer_end = outer_span
    inner_path, inner_start, inner_end = inner_span
    return (
        outer_path == inner_path
        and outer_start <= inner_start
        and outer_end >= inner_end
        and (outer_start, outer_end) != (inner_start, inner_end)
    )


def _side_span(
    change: SymbolChange, side: str
) -> tuple[str, int, int] | None:
    if side == "base":
        path = change.base_file_path or change.file_path
        start, end = change.base_start_line, change.base_end_line
    else:
        path = change.file_path
        start, end = change.target_start_line, change.target_end_line
    if start is None or end is None:
        return None
    return path, start, end


def _signature_change_class(
    base_signature: str | None,
    target_signature: str | None,
) -> SignatureChangeClass:
    if base_signature == target_signature:
        return SignatureChangeClass.NONE
    base_norm = _normalize_signature(base_signature)
    target_norm = _normalize_signature(target_signature)
    if base_norm == target_norm:
        return SignatureChangeClass.NONE
    if _only_optional_parameters_added(base_norm, target_norm):
        return SignatureChangeClass.ONLY_OPTIONAL_PARAMETERS_ADDED
    return SignatureChangeClass.OTHER


def _normalize_signature(signature: str | None) -> str:
    if signature is None:
        return ""
    # Strip TypeScript/JavaScript export modifiers so a pure export-keyword
    # change is handled by export findings, not signature findings.
    normalized = re.sub(r"^\s*export\s+", "", signature.strip())
    return " ".join(normalized.split())


def _only_optional_parameters_added(base: str, target: str) -> bool:
    base_params = _extract_parameters(base)
    target_params = _extract_parameters(target)
    if len(target_params) <= len(base_params):
        return False
    if target_params[: len(base_params)] != base_params:
        return False
    added = target_params[len(base_params) :]
    return all(_is_optional_parameter(param) for param in added)


def _extract_parameters(signature: str) -> list[str]:
    if not signature:
        return []
    match = re.search(r"\((.*)\)", signature)
    if not match:
        return []
    params_text = match.group(1).strip()
    if not params_text:
        return []

    params: list[str] = []
    depth = 0
    current: list[str] = []
    for char in params_text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            params.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        params.append("".join(current).strip())
    # `*` and `/` are separators, not parameters: gaining a keyword-only
    # marker alongside an optional parameter is still "only optional
    # parameters added" (c022).
    return [param for param in params if param not in {"*", "/"}]


def _is_optional_parameter(param: str) -> bool:
    text = param.strip()
    return "=" in text or text.endswith("?")
