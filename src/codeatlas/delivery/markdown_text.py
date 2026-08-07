"""Markdown escaping for untrusted repository text.

Everything rendered by a delivery renderer came out of a repository, which means
all of it is untrusted. A symbol named ``| --- |`` must not become a table row
separator, and a document heading containing a backtick fence must not end a
code block early.

This lives in its own module because more than one renderer needs it. Two copies
would be two places to get it wrong, and only one of them would be reviewed when
someone next changed it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Final

# Control characters would let repository content move the cursor or blank a
# line in a terminal that renders the Markdown.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_CELL_LENGTH: Final[int] = 160


def escape_inline(value: str) -> str:
    """Escape a value for inline Markdown.

    Backticks are the dangerous ones: repository text containing one can close a
    code span and let the rest render as markup. Pipes are escaped too so a
    value interpolated near a table cannot introduce a column.
    """
    text = _CONTROL.sub("", value)
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def escape_cell(value: str) -> str:
    """Escape a value for a table cell and bound its length.

    A cell is truncated rather than wrapped: an unbounded value from repository
    content would push a table past any width and make the whole report
    unreadable.
    """
    text = escape_inline(value)
    if len(text) > MAX_CELL_LENGTH:
        return text[: MAX_CELL_LENGTH - 1] + "…"
    return text


def table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    """Render one Markdown table, header and separator included."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines
