"""Editing a Markdown document must not delete the sections it keeps.

A real preflight over this repository reported 524 `SYMBOL_DELETED` findings
for headings present in both states. These tests reproduce that in-process,
because the engine parses both full states on every analysis and the real loop
is a quarter of an hour.
"""

from __future__ import annotations

from collections.abc import Sequence

from codeatlas.analysis.symbol_diff import SymbolDiffInput, compute_symbol_changes
from codeatlas.contracts import ChangeKind
from codeatlas.domain.change import SymbolChange
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.document_parser import DocumentParser
from codeatlas.parsing.registry import ParseRequest

_PATH = "docs/notes.md"


def _sections(
    markdown: str,
    path: str = _PATH,
    file_id: str | None = None,
) -> tuple[FileRecord, tuple[SymbolRecord, ...]]:
    """Parse `markdown` into the section symbols the diff consumes."""
    content = markdown.encode("utf-8")
    resolved_id = file_id or f"file_{path}"
    record = FileRecord(
        file_id=resolved_id,
        relative_path=path,
        display_path=path,
        content_hash=f"hash_{len(content)}",
        size_bytes=len(content),
        line_count=content.count(b"\n") + (0 if content.endswith(b"\n") else 1),
        language="markdown",
        classification=FileClassification.DOCUMENTATION,
    )
    result = DocumentParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id=resolved_id,
            relative_path=path,
            language="markdown",
            content=content,
        )
    )
    return record, result.symbols


def _input(symbols: tuple[SymbolRecord, ...], record: FileRecord) -> SymbolDiffInput:
    return SymbolDiffInput(
        symbols=symbols,
        relations=(),
        file_paths={record.file_id: record.relative_path},
    )


def _deleted(changes: Sequence[SymbolChange]) -> list[str]:
    return [
        change.qualified_name
        for change in changes
        if change.change_kind is ChangeKind.DELETED
    ]


_BEFORE = """# Title

## Kept One

Text.

## Kept Two

Text.
"""

_AFTER = """# Title

## Inserted

New text.

## Kept One

Text.

## Kept Two

Text.
"""


def test_inserting_a_section_does_not_delete_the_sections_it_keeps() -> None:
    base_record, base_symbols = _sections(_BEFORE)
    target_record, target_symbols = _sections(_AFTER)

    changes = compute_symbol_changes(
        _input(base_symbols, base_record),
        _input(target_symbols, target_record),
    )

    assert _deleted(changes) == []


def test_sections_pair_even_when_the_two_states_use_different_file_ids() -> None:
    """The base and target sides may not agree on a file's id.

    ADR-0042 made occurrences pair *within their file first*. If the id differs
    across states, nothing pairs within a file, which is the shape the real
    report showed: every section deleted, none added.
    """
    base_record, base_symbols = _sections(_BEFORE, file_id="file_base")
    target_record, target_symbols = _sections(_AFTER, file_id="file_target")

    changes = compute_symbol_changes(
        _input(base_symbols, base_record),
        _input(target_symbols, target_record),
    )

    assert _deleted(changes) == []


def test_a_target_read_mid_write_reports_every_section_deleted() -> None:
    """Pins the behaviour that produced a false report, so it stays diagnosable.

    On 2026-08-13 a preflight over this repository returned 496
    `SYMBOL_DELETED` findings for `PLAN.md`, one per section. The engine was
    right: the analysis ran for twelve minutes over a live working tree while
    the same session rewrote that file with `Path.write_text`, which truncates
    before it writes, and the read landed in that window.

    An empty target *should* report every section deleted -- that is what an
    empty file means. The test exists so the next person who sees a wall of
    deletions can tell this shape apart from a pairing defect in one run:
    deletions equal to the section count, with no additions, means the target
    was not there to be read.
    """
    base_record, base_symbols = _sections(_BEFORE)
    target_record, target_symbols = _sections("")

    changes = compute_symbol_changes(
        _input(base_symbols, base_record),
        _input(target_symbols, target_record),
    )

    assert _deleted(changes) == ["Kept One", "Kept Two", "Title"]
    assert [c for c in changes if c.change_kind is ChangeKind.ADDED] == []
