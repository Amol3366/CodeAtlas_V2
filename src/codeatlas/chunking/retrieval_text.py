"""Deterministic retrieval text.

Retrieval text is what lexical search reads and what a later semantic layer
would embed. It is built only from parsed facts — path, language, symbol
identity, line range, and the file's own bytes. Nothing here summarizes,
paraphrases, or invents: a header a model could hallucinate would be a header a
reader cannot verify against the file.

The text is bounded on purpose. Chunk rows are a search projection, not a second
copy of the repository, so evidence is still re-read from disk and hash-verified
before it is cited.
"""

from __future__ import annotations

from collections.abc import Sequence

from codeatlas.contracts import SymbolKind
from codeatlas.domain.repository import FileClassification

_MAX_DOCSTRING_CHARACTERS = 400
_MAX_MEMBERS = 60


def build_symbol_retrieval_text(
    *,
    relative_path: str,
    language: str,
    qualified_name: str,
    kind: SymbolKind,
    parent: str | None,
    signature: str | None,
    docstring: str | None,
    start_line: int,
    end_line: int,
    code: str,
    members: Sequence[str] = (),
    part_index: int = 0,
    part_count: int = 1,
) -> str:
    """Render one symbol chunk's retrieval text.

    ``members`` is used for container symbols — a module or a class — which
    name what they contain instead of repeating its bodies. ``code`` is used for
    leaf symbols, which are small enough to carry verbatim.
    """
    lines = [
        f"PATH: {relative_path}",
        f"LANGUAGE: {language}",
        f"SYMBOL: {qualified_name}",
        f"TYPE: {kind.value}",
    ]
    if parent:
        lines.append(f"PARENT: {parent}")
    lines.append(f"LINES: {start_line}-{end_line}")
    if part_count > 1:
        lines.append(f"PART: {part_index + 1} of {part_count}")
    if signature:
        lines.append(f"SIGNATURE: {signature}")
    if docstring:
        lines.append(f"DOCSTRING: {_condense(docstring)}")
    if members:
        listed = list(members[:_MAX_MEMBERS])
        if len(members) > _MAX_MEMBERS:
            listed.append(f"... and {len(members) - _MAX_MEMBERS} more")
        lines.append("MEMBERS: " + ", ".join(listed))
    lines.append("CODE:")
    lines.append(code)
    return "\n".join(lines)


def build_file_summary_text(
    *,
    relative_path: str,
    language: str,
    classification: FileClassification,
    exported_symbols: Sequence[str],
    line_count: int,
) -> str:
    """Render a file's summary chunk from metadata alone.

    Deliberately free of prose: everything here is a fact already recorded in
    the file record or the symbol table, so the summary cannot drift from what
    was actually indexed.
    """
    listed = list(exported_symbols[:_MAX_MEMBERS])
    if len(exported_symbols) > _MAX_MEMBERS:
        listed.append(f"... and {len(exported_symbols) - _MAX_MEMBERS} more")
    return "\n".join(
        [
            f"PATH: {relative_path}",
            f"LANGUAGE: {language}",
            "TYPE: file_summary",
            f"CLASSIFICATION: {classification.value}",
            f"LINES: 1-{max(line_count, 1)}",
            "SYMBOLS: " + (", ".join(listed) if listed else "(none)"),
        ]
    )


def build_document_retrieval_text(
    *,
    relative_path: str,
    language: str,
    title: str,
    heading_path: str,
    start_line: int,
    end_line: int,
    body: str,
    part_index: int = 0,
    part_count: int = 1,
) -> str:
    """Render one document section's retrieval text.

    The heading ancestry travels with the chunk so a fragment retrieved on its
    own can still be placed inside the document it came from.
    """
    lines = [
        f"PATH: {relative_path}",
        f"LANGUAGE: {language}",
        f"SECTION: {title}",
        "TYPE: document_section",
    ]
    if heading_path:
        lines.append(f"HEADING PATH: {heading_path}")
    lines.append(f"LINES: {start_line}-{end_line}")
    if part_count > 1:
        lines.append(f"PART: {part_index + 1} of {part_count}")
    lines.append("TEXT:")
    lines.append(body)
    return "\n".join(lines)


def build_config_retrieval_text(
    *,
    relative_path: str,
    language: str,
    key: str,
    nested_paths: Sequence[str],
    start_line: int,
    end_line: int,
    body: str,
) -> str:
    """Render one configuration key's retrieval text.

    Nested structure is summarized as dotted key paths rather than repeated as
    raw configuration, so searching for ``scripts.build`` finds the key group
    that defines it.
    """
    lines = [
        f"PATH: {relative_path}",
        f"LANGUAGE: {language}",
        f"KEY: {key}",
        "TYPE: config_key",
        f"LINES: {start_line}-{end_line}",
    ]
    if nested_paths:
        listed = list(nested_paths[:_MAX_MEMBERS])
        if len(nested_paths) > _MAX_MEMBERS:
            listed.append(f"... and {len(nested_paths) - _MAX_MEMBERS} more")
        lines.append("NESTED KEYS: " + ", ".join(listed))
    lines.append("VALUE:")
    lines.append(body)
    return "\n".join(lines)


def _condense(text: str) -> str:
    """Collapse a docstring to one bounded line."""
    condensed = " ".join(text.split())
    if len(condensed) > _MAX_DOCSTRING_CHARACTERS:
        return condensed[:_MAX_DOCSTRING_CHARACTERS] + "..."
    return condensed
