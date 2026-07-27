"""Structural parsing of documents and configuration.

Documents are untrusted input. A Markdown file may contain HTML, scripts, or
text that reads like an instruction; all of it is data. This module reads
structure only — headings, key names, line ranges — and never interprets,
rewrites, executes, or obeys what it reads.

Deserialization is deliberately narrow:

* JSON goes through the standard library's ``json``;
* TOML goes through ``tomllib``;
* YAML is scanned **line by line**. Phase 2 adds no YAML dependency, and the
  safe loader that would justify one is not available without it. The scanner
  reports only what it can read unambiguously — top-level keys and their line
  ranges — and emits a diagnostic instead of guessing at anything else.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.errors import PathSafetyError
from codeatlas.domain.ids import symbol_id, symbol_version_id
from codeatlas.domain.paths import validate_relative_path
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.extraction.routes import (
    MAX_MENTIONS_PER_SECTION,
    MENTION_HINT,
    ROUTE_HINT,
    mention_words,
    routes_in_text,
)
from codeatlas.parsing.registry import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)

MAX_DOCUMENT_BYTES = 1_000_000
MAX_HEADING_LENGTH = 200
MAX_NESTED_KEY_PATHS = 40

# Longest first, so "MUST NOT" is never reported as a bare "MUST".
_NORMATIVE_TERMS = ("MUST NOT", "MUST", "SHOULD NOT", "SHOULD", "MAY")

_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_YAML_KEY = re.compile(r"^(?P<key>[A-Za-z_][\w.-]*)\s*:(?:\s|$)")
# A repository-relative path reference: at least one directory separator and a
# short extension. Deliberately narrow — prose is full of dotted abbreviations,
# and a false reference is worse than a missed one.
_PATH_REFERENCE = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}")


@dataclass(frozen=True)
class DocumentSection:
    """One heading and the body that belongs to it."""

    heading_path: tuple[str, ...]
    title: str
    start_line: int
    end_line: int
    normative_terms: tuple[str, ...] = ()
    referenced_paths: tuple[str, ...] = ()


class DocumentParser:
    """Extracts sections and configuration keys. Reads only; runs nothing."""

    name = "document"
    version = PARSER_BUNDLE_VERSION
    supported_languages = frozenset({"markdown", "json", "yaml", "toml"})

    def parse(self, request: ParseRequest) -> ParseResult:
        guard = self._reject(request)
        if guard is not None:
            return guard

        text = request.content.decode("utf-8-sig")
        if request.language == "markdown":
            sections = _markdown_sections(text)
            symbols = _section_symbols(request, sections)
            return self._result(
                request,
                symbols=symbols,
                success=True,
                references=_document_references(
                    file_id=request.file_id,
                    text=text,
                    sections=sections,
                    symbols=symbols,
                ),
            )

        keys, diagnostics = _configuration_keys(request.language, text)
        if diagnostics:
            return self._result(request, symbols=(), success=False, extra=diagnostics)
        return self._result(
            request, symbols=_config_symbols(request, keys), success=True
        )

    def sections(self, request: ParseRequest) -> tuple[DocumentSection, ...]:
        """Return Markdown sections, or an empty tuple for anything else."""
        if self._reject(request) is not None or request.language != "markdown":
            return ()
        return _markdown_sections(request.content.decode("utf-8-sig"))

    def _reject(self, request: ParseRequest) -> ParseResult | None:
        if request.language not in self.supported_languages:
            return self._failed(
                request,
                "PARSE_UNSUPPORTED",
                "The document language is not supported by this parser.",
            )
        if len(request.content) > MAX_DOCUMENT_BYTES:
            return self._failed(
                request,
                "PARSE_FILE_TOO_LARGE",
                "The document exceeds the maximum parseable size.",
            )
        try:
            request.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return self._failed(
                request,
                "PARSE_ENCODING_ERROR",
                "The document is not valid UTF-8 text.",
            )
        return None

    def _result(
        self,
        request: ParseRequest,
        *,
        symbols: tuple[SymbolRecord, ...],
        success: bool,
        extra: Sequence[ParseDiagnostic] = (),
        references: tuple[SymbolReference, ...] = (),
    ) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=success,
            symbols=symbols,
            diagnostics=tuple(extra),
            references=references,
        )

    def _failed(self, request: ParseRequest, code: str, message: str) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=False,
            symbols=(),
            diagnostics=(ParseDiagnostic(code=code, message=message),),
        )


def _markdown_sections(text: str) -> tuple[DocumentSection, ...]:
    lines = text.splitlines()
    headings = list(_headings(lines))
    sections: list[DocumentSection] = []
    ancestry: list[tuple[int, str]] = []

    for index, (line_number, level, title) in enumerate(headings):
        while ancestry and ancestry[-1][0] >= level:
            ancestry.pop()
        ancestry.append((level, title))

        end_line = (
            headings[index + 1][0] - 1
            if index + 1 < len(headings)
            else max(len(lines), line_number)
        )
        body = "\n".join(lines[line_number - 1 : end_line])
        sections.append(
            DocumentSection(
                heading_path=tuple(name for _, name in ancestry),
                title=title,
                start_line=line_number,
                end_line=max(end_line, line_number),
                normative_terms=_normative_terms(body),
                referenced_paths=_referenced_paths(body),
            )
        )
    return tuple(sections)


def _headings(lines: Sequence[str]) -> Iterator[tuple[int, int, str]]:
    """Yield ``(line_number, level, title)``, ignoring fenced code blocks."""
    in_fence = False
    for offset, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING.match(line)
        if match is not None:
            title = match.group("title").strip()[:MAX_HEADING_LENGTH]
            if title:
                yield offset, len(match.group("hashes")), title


def _normative_terms(body: str) -> tuple[str, ...]:
    found: list[str] = []
    remaining = body
    for term in _NORMATIVE_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", remaining):
            found.append(term)
            remaining = re.sub(rf"\b{re.escape(term)}\b", " ", remaining)
    return tuple(found)


def _referenced_paths(body: str) -> tuple[str, ...]:
    """Return repository-relative paths named in the text.

    A candidate is recorded only when it survives the same validation a real
    path must pass, so a traversal or absolute path named in prose is never
    stored as if it were a repository location.
    """
    seen: list[str] = []
    for candidate in _PATH_REFERENCE.findall(body):
        try:
            validated = validate_relative_path(candidate)
        except PathSafetyError:
            continue
        if validated not in seen:
            seen.append(validated)
    return tuple(seen)


def _document_references(
    *,
    file_id: str,
    text: str,
    sections: Sequence[DocumentSection],
    symbols: Sequence[SymbolRecord],
) -> tuple[SymbolReference, ...]:
    """Record the paths and words each section names.

    None of this is an edge. A document that writes ``/health`` has stated a
    path, and a document that writes "port" has used a word; whether either one
    names something in this repository cannot be known from one file. Resolution
    answers that, and labels whatever it concludes as the heuristic it is.

    Mentions are capped per section because a document is untrusted input of
    unbounded length, and one reference per word would let a file dictate how
    much work resolution does.
    """
    lines = text.splitlines()
    references: list[SymbolReference] = []

    for section, symbol in zip(sections, symbols, strict=True):
        routes: dict[str, int] = {}
        words: dict[str, int] = {}
        body = lines[section.start_line - 1 : section.end_line]
        for offset, line in enumerate(body, start=section.start_line):
            for route in routes_in_text(line):
                routes.setdefault(route, offset)
            for word in mention_words(line):
                if len(words) >= MAX_MENTIONS_PER_SECTION and word not in words:
                    break
                words.setdefault(word, offset)

        for hint, (target, line_number) in (
            *((ROUTE_HINT, item) for item in routes.items()),
            *((MENTION_HINT, item) for item in words.items()),
        ):
            references.append(
                SymbolReference(
                    source_symbol_id=symbol.symbol_id,
                    file_id=file_id,
                    kind=RelationKind.DOCUMENTS,
                    target_hint=target,
                    module_hint=hint,
                    start_line=line_number,
                    end_line=line_number,
                )
            )
    return tuple(references)


@dataclass(frozen=True)
class _ConfigKey:
    """One top-level configuration key and the lines it occupies."""

    name: str
    start_line: int
    end_line: int
    nested_paths: tuple[str, ...]


def _configuration_keys(
    language: str, text: str
) -> tuple[tuple[_ConfigKey, ...], tuple[ParseDiagnostic, ...]]:
    if language == "json":
        return _json_keys(text)
    if language == "toml":
        return _toml_keys(text)
    return _yaml_keys(text)


def _json_keys(
    text: str,
) -> tuple[tuple[_ConfigKey, ...], tuple[ParseDiagnostic, ...]]:
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as error:
        return (), (
            ParseDiagnostic(
                code="PARSE_SYNTAX_ERROR",
                message="The file could not be parsed as JSON.",
                start_line=getattr(error, "lineno", None),
            ),
        )
    if not isinstance(document, dict):
        return (), (
            ParseDiagnostic(
                code="PARSE_UNSUPPORTED",
                message="Only a JSON object has top-level configuration keys.",
            ),
        )
    lines = text.splitlines()
    starts = [
        (str(name), _first_line_matching(lines, rf'"{re.escape(str(name))}"'))
        for name in document
    ]
    # The top-level object's own closing brace belongs to no key, so the last
    # key's block stops before it. Only that one brace is trimmed: a nested
    # object's closing brace is part of the key that contains it.
    last_line = len(lines)
    while last_line > 1 and not lines[last_line - 1].strip():
        last_line -= 1
    if last_line > 1 and lines[last_line - 1].strip() in {"}", "]"}:
        last_line -= 1
    return (
        tuple(
            _ConfigKey(
                name=name,
                start_line=start,
                end_line=_block_end(starts, index, start, last_line),
                nested_paths=_nested_paths(name, document[name]),
            )
            for index, (name, start) in enumerate(starts)
        ),
        (),
    )


def _toml_keys(
    text: str,
) -> tuple[tuple[_ConfigKey, ...], tuple[ParseDiagnostic, ...]]:
    try:
        document = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError):
        return (), (
            ParseDiagnostic(
                code="PARSE_SYNTAX_ERROR",
                message="The file could not be parsed as TOML.",
            ),
        )
    lines = text.splitlines()
    starts = [
        (
            name,
            _first_line_matching(
                lines,
                rf"^\s*(?:\[\[?{re.escape(name)}\b|{re.escape(name)}\s*=)",
            ),
        )
        for name in document
    ]
    last_line = len(lines)
    while last_line > 1 and not lines[last_line - 1].strip():
        last_line -= 1
    return (
        tuple(
            _ConfigKey(
                name=name,
                start_line=start,
                end_line=_block_end(starts, index, start, last_line),
                nested_paths=_nested_paths(name, document[name]),
            )
            for index, (name, start) in enumerate(starts)
        ),
        (),
    )


def _yaml_keys(
    text: str,
) -> tuple[tuple[_ConfigKey, ...], tuple[ParseDiagnostic, ...]]:
    """Scan top-level YAML keys by line. No YAML library is used or wanted."""
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    in_fence = False
    for offset, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("---") or not stripped or stripped.startswith("#"):
            continue
        if stripped in {"|", ">"}:
            in_fence = not in_fence
            continue
        if line[:1].isspace():
            continue
        match = _YAML_KEY.match(line)
        if match is None:
            # A top-level construct this scanner cannot read unambiguously.
            return (), (
                ParseDiagnostic(
                    code="PARSE_UNSUPPORTED",
                    message=(
                        "The YAML file uses a top-level construct the line "
                        "scanner does not interpret."
                    ),
                    start_line=offset,
                ),
            )
        found.append((offset, match.group("key")))

    if not found:
        return (), (
            ParseDiagnostic(
                code="PARSE_UNSUPPORTED",
                message="No top-level YAML keys were found.",
            ),
        )

    keys: list[_ConfigKey] = []
    for index, (line_number, name) in enumerate(found):
        end_line = (
            found[index + 1][0] - 1 if index + 1 < len(found) else max(len(lines), 1)
        )
        keys.append(
            _ConfigKey(
                name=name,
                start_line=line_number,
                end_line=max(end_line, line_number),
                nested_paths=_yaml_nested_paths(
                    name, lines[line_number : max(end_line, line_number)]
                ),
            )
        )
    return tuple(keys), ()


def _yaml_nested_paths(prefix: str, body: Sequence[str]) -> tuple[str, ...]:
    """Dotted paths under one top-level YAML key, read by indentation.

    This is the same bounded summary JSON and TOML already carry. It is what
    lets a reader name ``service.port`` rather than the whole ``service`` block,
    while the citation still points at the block, because a key without its
    value is half a fact.

    A line the scanner cannot read unambiguously is skipped rather than guessed
    at; the top-level key is already recorded, so nothing is silently lost.
    """
    paths: list[str] = []
    stack: list[tuple[int, str]] = []

    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        match = _YAML_KEY.match(stripped)
        if match is None:
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else prefix
        path = f"{parent}.{match.group('key')}"
        stack.append((indent, path))
        if path not in paths:
            paths.append(path)
        if len(paths) >= MAX_NESTED_KEY_PATHS:
            break
    return tuple(paths)


def _nested_paths(prefix: str, value: Any) -> tuple[str, ...]:
    """Summarize nested structure as bounded dotted key paths."""
    paths: list[str] = []

    def walk(current: str, node: Any, depth: int) -> None:
        if len(paths) >= MAX_NESTED_KEY_PATHS or depth > 6:
            return
        if isinstance(node, Mapping):
            for name, child in node.items():
                path = f"{current}.{name}"
                paths.append(path)
                walk(path, child, depth + 1)

    walk(prefix, value, 0)
    return tuple(paths[:MAX_NESTED_KEY_PATHS])


def _block_end(
    starts: Sequence[tuple[str, int]], index: int, start: int, last_line: int
) -> int:
    """Where a top-level key's block ends: just before the next one begins.

    A configuration key is only meaningful together with its value, so citing
    the line the name appears on would point a reader at half the fact.
    """
    later = [line for _, line in starts[index + 1 :] if line > start]
    end = min(later) - 1 if later else last_line
    return max(end, start)


def _first_line_matching(lines: Sequence[str], pattern: str) -> int:
    expression = re.compile(pattern)
    for offset, line in enumerate(lines, start=1):
        if expression.search(line):
            return offset
    return 1


def _section_symbols(
    request: ParseRequest, sections: Sequence[DocumentSection]
) -> tuple[SymbolRecord, ...]:
    titles = [section.title for section in sections]
    records: list[SymbolRecord] = []
    for section in sections:
        # A repeated title would collide as an identity, so it falls back to its
        # full ancestry, which is unique by construction.
        unique = titles.count(section.title) == 1
        qualified_name = section.title if unique else " > ".join(section.heading_path)
        records.append(
            _record(
                request=request,
                kind=SymbolKind.DOCUMENT_SECTION,
                name=section.title,
                qualified_name=qualified_name,
                container=" > ".join(section.heading_path),
                start_line=section.start_line,
                end_line=section.end_line,
            )
        )
    return tuple(records)


def _config_symbols(
    request: ParseRequest, keys: Sequence[_ConfigKey]
) -> tuple[SymbolRecord, ...]:
    return tuple(
        _record(
            request=request,
            kind=SymbolKind.CONFIG_KEY,
            name=key.name,
            qualified_name=key.name,
            container=", ".join(key.nested_paths),
            start_line=key.start_line,
            end_line=key.end_line,
        )
        for key in keys
    )


def _record(
    *,
    request: ParseRequest,
    kind: SymbolKind,
    name: str,
    qualified_name: str,
    container: str,
    start_line: int,
    end_line: int,
) -> SymbolRecord:
    """Build one document symbol.

    ``module_path`` carries the structural context a document has instead of a
    module: a heading ancestry, or the dotted nested keys under a configuration
    key. The chunker reads it back rather than re-deriving structure.
    """
    lines = request.content.decode("utf-8-sig").splitlines()
    body = "\n".join(lines[start_line - 1 : end_line])
    logical = symbol_id(
        request.repository_id, request.relative_path, qualified_name, kind.value
    )
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return SymbolRecord(
        symbol_id=logical,
        symbol_version_id=symbol_version_id(
            logical, content_hash, PARSER_BUNDLE_VERSION
        ),
        file_id=request.file_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        module_path=container,
        signature=None,
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=0,
        content_hash=content_hash,
        visibility="public",
    )
