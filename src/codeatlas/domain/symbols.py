"""Parsed symbol records.

``symbol_id`` is logical identity and survives edits to the symbol's body.
``symbol_version_id`` additionally covers the content and the parser bundle, so
it changes whenever either does. Keeping both is what lets a later phase reuse
unchanged work while still recomputing what actually moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from codeatlas.contracts import SymbolKind

Visibility = Literal["public", "private"]


@dataclass(frozen=True)
class SymbolRecord:
    """One symbol definition located in one file of one snapshot."""

    symbol_id: str
    symbol_version_id: str
    file_id: str
    kind: SymbolKind
    name: str
    qualified_name: str
    module_path: str
    signature: str | None
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    content_hash: str
    visibility: Visibility
