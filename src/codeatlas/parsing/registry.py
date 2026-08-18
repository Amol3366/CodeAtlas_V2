"""Parser contracts and the language registry.

A parser converts file bytes into symbols. It is never allowed to import, run,
or resolve the code it reads, so a parse is a pure function of the request.

``PARSER_BUNDLE_VERSION`` participates in symbol version and snapshot identity:
changing parser behavior must invalidate previously derived artifacts, and a
single declared version is what makes that automatic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import SymbolRecord

# 1.1.0 (Phase 3, ADR-0004): parsers emit references alongside symbols, so every
# symbol version derived by the 1.0.0 bundle is stale.
# 1.2.0 (Phase 4, ADR-0005): parsers will emit route-literal references and
# document-section mention references, so every symbol version derived by the
# 1.1.0 bundle is stale. The behavior lands in P4-05; the constant lands in
# P4-SETUP so the identity change is in place before the behavior that depends
# on it, following the Phase 3 precedent.
# 1.2.1: TypeScript/JavaScript property signatures inherit the nearest named
# declaration as context, and repeated anonymous type members are position
# disambiguated. This prevents unrelated inline object/type properties with the
# same name from colliding inside one snapshot.
# 1.4.0: a nested configuration key hashes its own value rather than the line
# range it cites. ADR-0025 gave a leaf whose line could not be located its
# parent's range so a citation was never invented, and hashing that range made
# the leaf hash the whole parent block -- so one `version` edit in a
# `pyproject.toml` reported eight keys changed, seven of them falsely. The
# range still cites; the hash now identifies. Symbol identity moves, so every
# snapshot is stale until re-indexed.
PARSER_BUNDLE_VERSION: str = "1.4.0"


@dataclass(frozen=True)
class ParseRequest:
    """Everything a parser is allowed to know about a file."""

    repository_id: str
    snapshot_id: str
    file_id: str
    relative_path: str
    language: str
    content: bytes


@dataclass(frozen=True)
class ParseDiagnostic:
    """A bounded, non-fatal parsing problem."""

    code: str
    message: str
    start_line: int | None = None


@dataclass(frozen=True)
class ParseResult:
    """Symbols, references, and diagnostics produced from one file.

    ``references`` are what the file *said*, not what those statements resolve
    to. Resolution needs the whole snapshot and happens later; keeping the two
    apart is what lets an unchanged file's references be reused verbatim.

    It defaults to empty so a parser that emits no references — or one written
    before they existed — stays valid rather than silently reporting a partial
    set.
    """

    parser_name: str
    parser_version: str
    success: bool
    symbols: tuple[SymbolRecord, ...]
    diagnostics: tuple[ParseDiagnostic, ...]
    references: tuple[SymbolReference, ...] = ()


class LanguageParser(Protocol):
    """The contract every language parser satisfies."""

    name: str
    version: str
    supported_languages: frozenset[str]

    def parse(self, request: ParseRequest) -> ParseResult: ...


class ParserRegistry:
    """Maps a detected language to the parser that handles it."""

    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParser] = {}

    def register(self, parser: LanguageParser) -> None:
        """Register a parser, refusing to shadow an existing language.

        Silent replacement would make symbol extraction depend on import order,
        so a duplicate is an error.
        """
        for language in parser.supported_languages:
            if language in self._parsers:
                raise ValueError(f"a parser is already registered for {language!r}")
            self._parsers[language] = parser

    def parser_for(self, language: str) -> LanguageParser | None:
        """Return the parser for ``language``, or ``None`` when unsupported."""
        return self._parsers.get(language)


def default_registry() -> ParserRegistry:
    """Build the registry: Python, TypeScript/JavaScript, documents, config."""
    from codeatlas.parsing.document_parser import DocumentParser
    from codeatlas.parsing.python_parser import PythonParser
    from codeatlas.parsing.query_backed.engine import TagsBackedParser
    from codeatlas.parsing.query_backed.languages.java import JavaAdapter
    from codeatlas.parsing.tsjs_parser import TsJsParser

    registry = ParserRegistry()
    registry.register(PythonParser())
    registry.register(TsJsParser())
    registry.register(DocumentParser())
    # ADR-0065: query-backed languages. `register` refuses to shadow an
    # existing language, so a collision surfaces here rather than depending
    # on import order.
    registry.register(TagsBackedParser(JavaAdapter()))
    return registry
