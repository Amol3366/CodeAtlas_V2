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
PARSER_BUNDLE_VERSION: str = "1.1.0"


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
    from codeatlas.parsing.tsjs_parser import TsJsParser

    registry = ParserRegistry()
    registry.register(PythonParser())
    registry.register(TsJsParser())
    registry.register(DocumentParser())
    return registry
