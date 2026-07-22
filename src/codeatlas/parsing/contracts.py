"""Parser contracts (Blueprint §4.4.1-4.4.3, Phase 3).

Parse-time value objects, deliberately distinct from the persisted domain
entities (`domain/entities.py`) and API contracts. A parser is a pure function of
``(repository_id, relative_path, content)`` so parsing the same source twice
yields identical symbols/ids (idempotence). Diagnostics are first-class: parse
failures never raise out of a parser — they are recorded and returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from codeatlas.domain.enums import Derivation, Language, RelationType, SymbolType

# The parser bundle version participates in artifact identity (CLAUDE.md §2.14).
PARSER_BUNDLE_VERSION = "0.1.0"


@dataclass(frozen=True)
class ParsedSymbol:
    """A symbol produced by a parser (maps to domain Symbol at persist time)."""

    id: str
    qualified_name: str
    short_name: str
    symbol_type: SymbolType
    language: Language
    start_line: int
    end_line: int
    parent_id: str | None = None
    signature: str | None = None
    docstring: str | None = None
    exported: bool = True
    parser_confidence: float = 1.0


@dataclass(frozen=True)
class ParsedRelation:
    """A relation produced by a parser (maps to domain Relation at persist time).

    ``target_id`` is set only when the target was resolved to a local symbol;
    otherwise ``target_name`` carries the unresolved reference. ``CALLS`` requires
    ``derivation == static_resolved`` and confidence 1.0; every ``MAY_CALL`` must
    carry confidence < 1.0 and a heuristic derivation (CLAUDE.md §2.11).
    """

    id: str
    source_id: str
    relation_type: RelationType
    target_name: str
    confidence: float
    derivation: Derivation
    evidence_start_line: int
    evidence_end_line: int
    target_id: str | None = None


@dataclass(frozen=True)
class ParseDiagnostic:
    """A visible parse problem (never silently swallowed, CLAUDE.md §13)."""

    severity: str  # "error" | "warning" | "info"
    message: str
    line: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ParseRequest:
    """Input to a parser. ``relative_path`` is the normalized POSIX repo path."""

    repository_id: str
    relative_path: str
    language: Language
    content: bytes
    snapshot_id: str | None = None
    absolute_path: str | None = None


@dataclass(frozen=True)
class ParseResult:
    """Output of a parser: symbols, relations, and diagnostics."""

    parser_name: str
    parser_version: str
    language: Language
    relative_path: str
    success: bool
    symbols: tuple[ParsedSymbol, ...] = ()
    relations: tuple[ParsedRelation, ...] = ()
    diagnostics: tuple[ParseDiagnostic, ...] = field(default_factory=tuple)


@runtime_checkable
class LanguageParser(Protocol):
    """Common interface for all language parsers (Blueprint §4.4.1)."""

    name: str
    version: str
    supported_extensions: frozenset[str]

    def parse(self, request: ParseRequest) -> ParseResult: ...
