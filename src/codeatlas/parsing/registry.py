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

from codeatlas.domain.symbols import SymbolRecord

PARSER_BUNDLE_VERSION: str = "1.0.0"


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
    """Symbols and diagnostics produced from one file."""

    parser_name: str
    parser_version: str
    success: bool
    symbols: tuple[SymbolRecord, ...]
    diagnostics: tuple[ParseDiagnostic, ...]


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
    """Build the Phase 1 registry. Python is the only supported language."""
    from codeatlas.parsing.python_parser import PythonParser

    registry = ParserRegistry()
    registry.register(PythonParser())
    return registry
