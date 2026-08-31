"""Parsed symbol records.

``symbol_id`` is logical identity and survives edits to the symbol's body.
``symbol_version_id`` additionally covers the content and the parser bundle, so
it changes whenever either does. Keeping both is what lets a later phase reuse
unchanged work while still recomputing what actually moved.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal

from codeatlas.contracts import SymbolKind
from codeatlas.domain.ids import stable_hash, symbol_version_id

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


def ensure_unique_symbol_ids(
    symbols: tuple[SymbolRecord, ...],
    parser_bundle_version: str,
) -> tuple[SymbolRecord, ...]:
    """Give every symbol in one file a distinct ``symbol_id``.

    ``symbol_id`` is ``hash(repository_id, relative_path, qualified_name, kind)``
    and carries no disambiguator, so two symbols that legitimately share all
    four collapse onto one id -- and ``symbols`` is keyed
    ``(snapshot_id, symbol_id)``, which turns that into
    ``UNIQUE constraint failed`` and **no snapshot at all**. Six of seven
    languages can produce it: Python properties with their setters, Java and
    Scala overloads, Scala companion pairs, Go function-local types, Rust
    methods implemented for two traits or gated by two ``cfg`` attributes.

    **The first member of a collision group keeps its id untouched.** That is
    deliberate and is what makes this change free: a repository that indexes
    today has no collisions, so none of its ids move and no reindex is needed.
    Only ids that could never have been stored -- because their file could not
    be indexed at all -- are new.

    Later members are re-identified from the id they collided on, their
    signature, and their ordinal **within the same signature**. Using the
    signature first means a parser that knows it degrades gracefully: Python
    tells a property from its setter by ``(self)`` against ``(self, v)``, so
    those two stay stable when a third method is inserted between them. The
    query-backed tier reports ``signature is None`` for every language, so
    there the ordinal carries it alone, and inserting a same-named sibling
    above another shifts the later one's id. That is the known cost, and it is
    a smaller one than a repository that cannot be indexed: over-reporting a
    change is recoverable, a missing snapshot is not.

    Ordering is by ``start_byte`` so the result is deterministic for a given
    file rather than dependent on the order a parser happened to emit.
    """
    counts: dict[str, int] = {}
    for symbol in symbols:
        counts[symbol.symbol_id] = counts.get(symbol.symbol_id, 0) + 1
    if all(count == 1 for count in counts.values()):
        return symbols

    order = sorted(
        range(len(symbols)),
        key=lambda index: (symbols[index].start_byte, symbols[index].end_byte, index),
    )
    seen_group: set[str] = set()
    seen_signature: dict[tuple[str, str], int] = {}
    rewritten: dict[int, SymbolRecord] = {}

    for index in order:
        symbol = symbols[index]
        if counts[symbol.symbol_id] == 1:
            continue
        signature = symbol.signature or ""
        key = (symbol.symbol_id, signature)
        ordinal = seen_signature.get(key, 0)
        seen_signature[key] = ordinal + 1
        if symbol.symbol_id not in seen_group:
            # The first symbol of the group keeps the id it already had.
            seen_group.add(symbol.symbol_id)
            continue
        new_symbol_id = f"sym_{stable_hash(symbol.symbol_id, signature, str(ordinal))}"
        rewritten[index] = dataclasses.replace(
            symbol,
            symbol_id=new_symbol_id,
            symbol_version_id=symbol_version_id(
                new_symbol_id, symbol.content_hash, parser_bundle_version
            ),
        )

    return tuple(rewritten.get(index, symbol) for index, symbol in enumerate(symbols))
