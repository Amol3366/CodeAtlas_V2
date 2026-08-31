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
# 1.5.0 (ADR-0065): a query-backed parser emits Java symbols and references, so
# every symbol version derived by the 1.4.0 bundle is stale. RESOLVER_VERSION
# moves to 1.5.0 in the same change, deliberately: both make every snapshot
# stale, and landing them together costs users one reindex rather than two.
# 1.6.0 (ADR-0067): Scala emits CALLS edges for member calls -- `obj.method(x)`
# -- which its shipped `tags.scm` never captured. A Scala file therefore yields
# references it did not before, so every symbol version derived by the 1.5.0
# bundle is stale. RESOLVER_VERSION is deliberately NOT moved: resolution draws
# the same conclusions from a reference as it always did; only the set of
# references changed.
# 1.7.0 (ADR-0070): every query-backed file emits a compilation-unit MODULE
# symbol, and an import is attributed to it *and* to the file's first
# definition. A file therefore yields one symbol and one IMPORTS edge it did
# not before, so every symbol version derived by the 1.6.0 bundle is stale.
# RESOLVER_VERSION is deliberately NOT moved, on the ADR-0067 precedent:
# resolution draws the same conclusions from a reference as it always did.
# 1.8.0 (ADR-0071): Java and Scala emit a `signature` -- parameter types only,
# never parameter names -- so an overload's identity survives a same-named
# sibling being inserted above it. Every symbol row now carries a value where
# query-backed languages left NULL, so the 1.7.0 bundle's rows are stale.
# Go and Rust deliberately emit None: measured, a signature separates none of
# the collisions they actually produce. RESOLVER_VERSION unchanged again.
PARSER_BUNDLE_VERSION: str = "1.8.0"


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

    @property
    def languages(self) -> frozenset[str]:
        """Every language this registry can parse.

        `parser_for` answers "do you handle X?", which cannot enumerate. The
        contract's §5 language profile is guarded by deriving the list from
        here, so a language registered without the contract hearing about it
        fails a test rather than sitting unnoticed for two days as ADR-0065's
        four did.
        """
        return frozenset(self._parsers)


def default_registry() -> ParserRegistry:
    """Build the registry: Python, TypeScript/JavaScript, documents, config."""
    from codeatlas.parsing.document_parser import DocumentParser
    from codeatlas.parsing.python_parser import PythonParser
    from codeatlas.parsing.query_backed.engine import TagsBackedParser
    from codeatlas.parsing.query_backed.languages.go import GoAdapter
    from codeatlas.parsing.query_backed.languages.java import JavaAdapter
    from codeatlas.parsing.query_backed.languages.rust import RustAdapter
    from codeatlas.parsing.query_backed.languages.scala import ScalaAdapter
    from codeatlas.parsing.tsjs_parser import TsJsParser

    registry = ParserRegistry()
    registry.register(PythonParser())
    registry.register(TsJsParser())
    registry.register(DocumentParser())
    # ADR-0065: query-backed languages. `register` refuses to shadow an
    # existing language, so a collision surfaces here rather than depending
    # on import order.
    registry.register(TagsBackedParser(JavaAdapter()))
    registry.register(TagsBackedParser(GoAdapter()))
    registry.register(TagsBackedParser(RustAdapter()))
    registry.register(TagsBackedParser(ScalaAdapter()))
    return registry
