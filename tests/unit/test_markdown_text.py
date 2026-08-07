"""Escaping for untrusted repository text rendered as Markdown."""

from __future__ import annotations

from codeatlas.delivery.markdown_text import (
    MAX_CELL_LENGTH,
    escape_cell,
    escape_inline,
    table,
)


def test_a_backtick_cannot_close_a_code_span() -> None:
    # A symbol named with a backtick would otherwise end the span it sits in
    # and let the rest of the value render as markup.
    assert escape_inline("a`b") == "a\\`b"


def test_a_pipe_cannot_forge_a_table_column() -> None:
    assert escape_inline("a|b") == "a\\|b"


def test_angle_brackets_become_entities() -> None:
    assert escape_inline("<script>") == "&lt;script&gt;"


def test_a_newline_becomes_a_space() -> None:
    # A value spanning lines would break the row it belongs to.
    assert escape_inline("a\nb") == "a b"
    assert escape_inline("a\rb") == "a b"


def test_control_characters_are_removed() -> None:
    # These would move the cursor or blank a line in a terminal rendering it.
    assert escape_inline("a\x00\x1bb") == "ab"


def test_a_backslash_is_escaped_before_anything_else() -> None:
    # Escaping the backslash last would double-escape what earlier rules added.
    assert escape_inline("a\\b") == "a\\\\b"


def test_a_long_cell_is_truncated_rather_than_wrapped() -> None:
    # An unbounded value from repository content would push a table past any
    # width and make the whole report unreadable.
    result = escape_cell("x" * (MAX_CELL_LENGTH + 50))

    assert len(result) == MAX_CELL_LENGTH
    assert result.endswith("…")


def test_a_short_cell_is_unchanged_apart_from_escaping() -> None:
    assert escape_cell("a|b") == "a\\|b"


def test_a_table_has_a_header_a_separator_and_one_row_each() -> None:
    lines = table(("A", "B"), [("1", "2"), ("3", "4")])

    assert lines == ["| A | B |", "| --- | --- |", "| 1 | 2 |", "| 3 | 4 |"]


def test_a_table_with_no_rows_still_has_its_header() -> None:
    assert table(("A",), []) == ["| A |", "| --- |"]
