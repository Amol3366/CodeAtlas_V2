"""Symbol diff must not re-scan every relation once per symbol.

`_dependency_changed` and `_binding_span` filtered the *whole* relation list by
`source_symbol_id`, and both are called once per surviving symbol pair. Symbols
and relations both grow with the repository, so the cost was O(symbols x
relations) -- measured at a log-log exponent of **2.02** on a synthetic sweep
while every other stage sat at ~1.0.

**This is a complexity test, not a timing test.** It counts how many times the
relation sequence is traversed rather than how long the traversal takes, so it
is deterministic and cannot flake on a loaded machine. A quadratic
implementation traverses once per symbol; a grouped one traverses a fixed
number of times no matter how many symbols there are.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from codeatlas.analysis.symbol_diff import SymbolDiffInput, compute_symbol_changes
from codeatlas.contracts import Derivation, RelationKind, SymbolKind
from codeatlas.domain.relations import RelationRecord, ResolutionState
from codeatlas.domain.symbols import SymbolRecord

FILE_ID = "file_1"

# Generous. A grouped implementation traverses each side's relations a small
# fixed number of times (the binding maps, plus the grouping itself). The
# assertion is about *growth*, so the bound only has to sit far below the
# symbol count to separate O(n) from O(n^2).
MAX_TRAVERSALS = 12
SYMBOLS = 200


class _CountingRelations(Sequence[RelationRecord]):
    """A relation sequence that records every full traversal."""

    def __init__(self, records: tuple[RelationRecord, ...]) -> None:
        self._records = records
        self.traversals = 0

    def __iter__(self) -> Iterator[RelationRecord]:
        self.traversals += 1
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        return self._records[index]


def _symbol(index: int) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=f"sym_{index}",
        symbol_version_id=f"ver_{index}",
        file_id=FILE_ID,
        kind=SymbolKind.FUNCTION,
        name=f"handle_{index}",
        qualified_name=f"handle_{index}",
        module_path="src.app",
        signature=f"handle_{index}(value)",
        start_line=index * 3 + 1,
        end_line=index * 3 + 2,
        start_byte=index * 40,
        end_byte=index * 40 + 30,
        content_hash=f"hash_{index}",
        visibility="public",
    )


def _relation(index: int) -> RelationRecord:
    return RelationRecord(
        relation_id=f"rel_{index}",
        source_symbol_id=f"sym_{index}",
        target_symbol_id=None,
        file_id=FILE_ID,
        kind=RelationKind.CALLS,
        target_hint=f"helper_{index}",
        resolution=ResolutionState.UNRESOLVED,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.9,
        start_line=index * 3 + 2,
        end_line=index * 3 + 2,
        candidate_count=0,
    )


def _side() -> tuple[SymbolDiffInput, _CountingRelations]:
    """Both sides identical, which is the expensive path.

    A symbol whose content hash is unchanged is exactly the case that runs the
    dependency check, so an unchanged repository is the *worst* case rather
    than the cheapest one -- which is why this cost shows up on every preflight
    and not only on large diffs.
    """
    relations = _CountingRelations(tuple(_relation(i) for i in range(SYMBOLS)))
    return (
        SymbolDiffInput(
            symbols=tuple(_symbol(i) for i in range(SYMBOLS)),
            relations=relations,
            file_paths={FILE_ID: "src/app.py"},
        ),
        relations,
    )


def test_relations_are_not_rescanned_once_per_symbol() -> None:
    """The guard. Quadratic behaviour traverses ~once per symbol."""
    base, base_relations = _side()
    target, target_relations = _side()

    compute_symbol_changes(base, target)

    assert base_relations.traversals <= MAX_TRAVERSALS, (
        f"base relations traversed {base_relations.traversals} times for"
        f" {SYMBOLS} symbols; the scan is proportional to symbol count again"
    )
    assert target_relations.traversals <= MAX_TRAVERSALS, (
        f"target relations traversed {target_relations.traversals} times for"
        f" {SYMBOLS} symbols; the scan is proportional to symbol count again"
    )


def test_traversal_count_does_not_grow_with_symbol_count() -> None:
    """Growth, asserted directly rather than inferred from one bound.

    A fixed ceiling can be satisfied by an implementation that is merely
    *slow-growing*. Comparing two sizes separates a constant from a slope, and
    it is the assertion that would survive someone raising `MAX_TRAVERSALS`.
    """
    global SYMBOLS
    original = SYMBOLS
    try:
        SYMBOLS = 50
        small_base, small_relations = _side()
        small_target, _ = _side()
        compute_symbol_changes(small_base, small_target)

        SYMBOLS = 400
        large_base, large_relations = _side()
        large_target, _ = _side()
        compute_symbol_changes(large_base, large_target)
    finally:
        SYMBOLS = original

    assert large_relations.traversals == small_relations.traversals, (
        f"8x the symbols changed the traversal count"
        f" {small_relations.traversals} -> {large_relations.traversals};"
        " the work is proportional to symbols, not constant"
    )
