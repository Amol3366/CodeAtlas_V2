"""Resolution must not scan every symbol once per reference.

`resolution.py`'s module docstring has always claimed the pass is
O(references), not O(references x symbols). Three call sites contradicted it,
each iterating `symbols_by_id.values()` from inside a per-reference loop:
`_resolve_mention`, `_RouteIndex.handlers`, and `_derive_config_edges`. On this
repository -- 11,484 symbols and 160,541 references -- resolution took **310 s
of a 320 s preflight side**, and parsing, the stage everyone assumed was the
cost, took 8 s of it.

**This is a complexity test, not a timing test.** It counts how many times the
symbol table is traversed, which is deterministic and cannot flake on a loaded
machine. The distinction matters here specifically: the wall-clock numbers that
sent three earlier records to the wrong conclusion were taken on a machine whose
load moved an untouched path from 343 s to 549 s.

The bound is on *growth*, not on absolute work. An implementation that scans a
fixed number of times is linear no matter how large that fixed number is; one
that scans once per reference is the product, and only the second is a defect.
"""

from __future__ import annotations

from typing import Any

import pytest

from codeatlas.contracts import Derivation, RelationKind, SymbolKind
from codeatlas.domain.relations import (
    MENTION_HINT,
    ROUTE_HINT,
    RelationRecord,
    SymbolReference,
)
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.extraction import resolution
from codeatlas.extraction.resolution import SnapshotResolver

# Generous by design. Building the index legitimately walks the symbol table a
# few times, and the derivation passes walk it again. The assertion separates a
# constant from a slope, so the ceiling only has to sit far below the reference
# count.
MAX_SCANS = 12

DOC_FILE = "doc_file"
CODE_FILE = "code_file"


class _CountingSymbols(dict[str, SymbolRecord]):
    """A symbol table that records every full traversal of itself.

    `.values()` is how all three removed scans reached the whole snapshot, so
    counting it is counting exactly the thing this test exists to forbid.
    """

    def __init__(self, source: dict[str, SymbolRecord]) -> None:
        super().__init__(source)
        self.scans = 0

    def values(self) -> Any:
        self.scans += 1
        return super().values()


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[_CountingSymbols]:
    """Swap each built index's symbol table for a counting one."""
    built: list[_CountingSymbols] = []
    original = resolution._build_index

    def wrapped(files: Any, symbols: Any) -> Any:
        index = original(files, symbols)
        counting = _CountingSymbols(index.symbols_by_id)
        index.symbols_by_id = counting
        built.append(counting)
        return index

    monkeypatch.setattr(resolution, "_build_index", wrapped)
    return built


def _file(file_id: str, path: str, language: str) -> FileRecord:
    return FileRecord(
        file_id=file_id,
        relative_path=path,
        display_path=path,
        content_hash=f"hash_{file_id}",
        language=language,
        classification=FileClassification.SOURCE_CODE,
        size_bytes=100,
        line_count=10,
    )


def _symbol(index: int, kind: SymbolKind, name: str, file_id: str) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=f"sym_{index}",
        symbol_version_id=f"ver_{index}",
        file_id=file_id,
        kind=kind,
        name=name,
        qualified_name=name,
        module_path="src.app",
        signature=f"{name}()",
        start_line=index * 3 + 1,
        end_line=index * 3 + 2,
        start_byte=index * 40,
        end_byte=index * 40 + 30,
        content_hash=f"hash_{index}",
        visibility="public",
    )


def _state(
    *, symbols: int, references: int
) -> tuple[list[FileRecord], list[SymbolRecord], list[SymbolReference]]:
    """A document that names things, and code that could answer.

    Mentions and routes are the two reference classes that scanned the whole
    symbol table, so the state has to contain both to exercise what was fixed.
    """
    files = [
        _file(DOC_FILE, "docs/guide.md", "markdown"),
        _file(CODE_FILE, "src/app.py", "python"),
    ]
    section = _symbol(0, SymbolKind.DOCUMENT_SECTION, "Guide", DOC_FILE)
    handlers = [
        _symbol(index + 1, SymbolKind.FUNCTION, f"get_orders_{index}", CODE_FILE)
        for index in range(symbols)
    ]

    made: list[SymbolReference] = []
    for index in range(references):
        made.append(
            SymbolReference(
                source_symbol_id=section.symbol_id,
                file_id=DOC_FILE,
                kind=RelationKind.DOCUMENTS,
                target_hint=f"word_{index}",
                module_hint=MENTION_HINT,
                start_line=index + 1,
                end_line=index + 1,
            )
        )
        made.append(
            SymbolReference(
                source_symbol_id=section.symbol_id,
                file_id=DOC_FILE,
                kind=RelationKind.DOCUMENTS,
                target_hint=f"/orders/{index}",
                module_hint=ROUTE_HINT,
                start_line=index + 1,
                end_line=index + 1,
                part=1,
            )
        )
    return files, [section, *handlers], made


def test_symbol_table_is_not_scanned_once_per_reference(
    counted: list[_CountingSymbols],
) -> None:
    """The guard. A per-reference scan traverses ~once per reference."""
    files, symbols, references = _state(symbols=40, references=60)

    SnapshotResolver().resolve(files, symbols, references)

    assert len(counted) == 1
    assert counted[0].scans <= MAX_SCANS, (
        f"symbol table traversed {counted[0].scans} times for {len(references)}"
        " references; a per-reference scan of every symbol is back"
    )


def test_scan_count_does_not_grow_with_reference_count(
    counted: list[_CountingSymbols],
) -> None:
    """Growth, asserted directly rather than inferred from one ceiling.

    A fixed bound can be satisfied by an implementation that is merely
    slow-growing, and it is the assertion someone would defeat by raising
    `MAX_SCANS`. Comparing two sizes cannot be defeated that way.
    """
    small_files, small_symbols, small_references = _state(symbols=40, references=25)
    SnapshotResolver().resolve(small_files, small_symbols, small_references)

    large_files, large_symbols, large_references = _state(symbols=40, references=200)
    SnapshotResolver().resolve(large_files, large_symbols, large_references)

    small, large = counted
    assert large.scans == small.scans, (
        f"8x the references changed the scan count {small.scans} -> {large.scans};"
        " resolution work is proportional to references x symbols again"
    )


def test_scan_count_does_not_grow_with_symbol_count(
    counted: list[_CountingSymbols],
) -> None:
    """The other axis of the product, held to the same standard.

    Scanning once per *symbol* would be just as quadratic as scanning once per
    reference, and a fix that only indexed one direction would pass the test
    above while leaving the product intact.
    """
    small_files, small_symbols, small_references = _state(symbols=25, references=40)
    SnapshotResolver().resolve(small_files, small_symbols, small_references)

    large_files, large_symbols, large_references = _state(symbols=200, references=40)
    SnapshotResolver().resolve(large_files, large_symbols, large_references)

    small, large = counted
    assert large.scans == small.scans, (
        f"8x the symbols changed the scan count {small.scans} -> {large.scans};"
        " resolution work is proportional to references x symbols again"
    )


def _relation_keys(records: tuple[RelationRecord, ...]) -> set[tuple[str, str | None]]:
    return {(item.relation_id, item.target_symbol_id) for item in records}


def test_indexed_lookup_still_finds_the_same_targets() -> None:
    """Speed is worthless if the edges changed.

    The three indexes replaced predicates that ran against every symbol, so the
    risk is not that they are slower -- it is that a bucket key spells the
    predicate slightly differently. A mention matches case-insensitively on
    name; a route matches on shared word tokens; neither may match inside the
    file that stated it.
    """
    files = [
        _file(DOC_FILE, "docs/guide.md", "markdown"),
        _file(CODE_FILE, "src/app.py", "python"),
    ]
    section = _symbol(0, SymbolKind.DOCUMENT_SECTION, "Guide", DOC_FILE)
    # Case differs from the mention below, which the lowercased bucket must
    # still match.
    handler = _symbol(1, SymbolKind.FUNCTION, "GetOrders", CODE_FILE)
    # Excluded from mentions by kind, however well the name matches.
    module = _symbol(2, SymbolKind.MODULE, "getorders", CODE_FILE)
    # In the document's own file, so it is never its own answer.
    sibling = _symbol(3, SymbolKind.FUNCTION, "getorders", DOC_FILE)

    references = [
        SymbolReference(
            source_symbol_id=section.symbol_id,
            file_id=DOC_FILE,
            kind=RelationKind.DOCUMENTS,
            target_hint="getorders",
            module_hint=MENTION_HINT,
            start_line=1,
            end_line=1,
        ),
        SymbolReference(
            source_symbol_id=section.symbol_id,
            file_id=DOC_FILE,
            kind=RelationKind.DOCUMENTS,
            target_hint="/orders",
            module_hint=ROUTE_HINT,
            start_line=2,
            end_line=2,
        ),
    ]

    relations, _ = SnapshotResolver().resolve(
        files, [section, handler, module, sibling], references
    )

    by_hint = {item.target_hint: item for item in relations}
    mention = by_hint["getorders"]
    assert mention.target_symbol_id == handler.symbol_id, (
        "the mention must resolve to the differently-cased function, not to the"
        " module, the same-file sibling, or nothing"
    )
    assert mention.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC

    route = by_hint["/orders"]
    assert route.target_symbol_id == handler.symbol_id, (
        "`/orders` shares the word `orders` with `GetOrders`, and the token"
        " match must survive being precomputed at index build"
    )


def test_module_specifier_still_resolves_through_a_source_root() -> None:
    """The suffix index replaced a scan of the whole module table.

    `import app` must still find `src/pkg/app.py`, and the answer must stay the
    *first* such module rather than an arbitrary one, or two runs over the same
    repository could disagree.
    """
    files = [
        _file("f_first", "src/pkg/app.py", "python"),
        _file("f_second", "vendor/other/app.py", "python"),
        _file("f_caller", "src/pkg/main.py", "python"),
    ]
    target = _symbol(1, SymbolKind.FUNCTION, "run", "f_first")
    caller = _symbol(2, SymbolKind.FUNCTION, "main", "f_caller")
    references = [
        SymbolReference(
            source_symbol_id=caller.symbol_id,
            file_id="f_caller",
            kind=RelationKind.IMPORTS,
            target_hint="run",
            module_hint="pkg.app",
            start_line=1,
            end_line=1,
        )
    ]

    relations, _ = SnapshotResolver().resolve(files, [target, caller], references)

    assert relations[0].target_symbol_id == target.symbol_id, (
        "`pkg.app` must still match `src.pkg.app` by dotted suffix"
    )
