"""A parser driven by Tree-sitter queries rather than hand-written traversal.

Each grammar ships a ``tags.scm`` declaring its definitions and references. That
is enough for a symbol inventory and is *not* enough for a relation graph: no
shipped ``tags.scm`` captures an import (measured across nine grammars,
2026-08-19), and resolution is built on the import graph. Imports therefore come
from a query authored in this repository and interpreted by the adapter.

A parse is a pure function of its request. Nothing here reads a second file,
resolves a name, or executes anything (``AGENTS.md`` section 4.4).
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any

from tree_sitter import Parser as TreeSitterParser
from tree_sitter import QueryCursor

from codeatlas.contracts import SymbolKind
from codeatlas.domain.ids import symbol_id, symbol_version_id
from codeatlas.domain.symbols import SymbolRecord, ensure_unique_symbol_ids
from codeatlas.extraction.query_relations import extract_query_references
from codeatlas.parsing.query_backed.profile import LanguageAdapter
from codeatlas.parsing.registry import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)

MAX_PARSE_BYTES = 2_000_000


class TagsBackedParser:
    """Extracts symbols and references using a language's query profile."""

    def __init__(self, adapter: LanguageAdapter) -> None:
        self._adapter = adapter
        self._profile = adapter.profile
        self.name = f"query-{self._profile.language}"
        self.version = PARSER_BUNDLE_VERSION
        self.supported_languages = frozenset({self._profile.language})
        self._parser = TreeSitterParser(self._profile.grammar)

    def parse(self, request: ParseRequest) -> ParseResult:
        """Parse one file into symbols and references."""
        if not request.content:
            return self._empty()
        if len(request.content) > MAX_PARSE_BYTES:
            return self._failed(
                ParseDiagnostic(
                    code="PARSE_TOO_LARGE",
                    message="the file is larger than the parser will accept",
                )
            )
        tree = self._parser.parse(request.content)
        module_path = self._adapter.module_path(
            tree.root_node, request.content, request.relative_path
        )
        # The compilation unit is placed FIRST, because
        # `extract_query_references` attributes imports to
        # `symbols[0].symbol_id` (ADR-0070). An import then lands inside the
        # symbol it is labelled with, as it already does in Python and TS/JS,
        # instead of citing a line outside the class it attaches to.
        #
        # Before references, deliberately: reference extraction binds to
        # `symbols[0].symbol_id`, so the ids must be final by the time it runs.
        definitions = self._definitions(tree.root_node, request, module_path)
        symbols = ensure_unique_symbol_ids(
            (
                self._compilation_unit(tree.root_node, request, module_path),
                *(record for record, _ in definitions),
            ),
            PARSER_BUNDLE_VERSION,
            # Positionally parallel, and the compilation unit leads with None:
            # it is one per file and cannot collide with itself (ADR-0074).
            (None, *(discriminator for _, discriminator in definitions)),
        )
        references = extract_query_references(
            tree.root_node, request.content, request, self._adapter, symbols
        )
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            symbols=symbols,
            diagnostics=(),
            references=references,
        )

    def _compilation_unit(
        self, root: Any, request: ParseRequest, module_path: str
    ) -> SymbolRecord:
        """One MODULE symbol covering the whole file.

        ADR-0070. Python and TS/JS attach a file-level
        import to a MODULE spanning the file, so the import line sits *inside*
        its source symbol. No query-backed adapter emits such a symbol, so an
        import attaches to the class instead and cites a line outside it -- 4 of
        4 query-backed languages, against 3 of 3 inside for the full-engine
        tier.

        **The range is clamped, and that is not incidental.** tree-sitter's root
        node ends one line past a trailing newline, so a naive whole-file range
        fails snapshot validation with "a staged symbol has a line range outside
        its file". That was measured on 2026-08-22 and is the reason this is not
        the six-line change it looks like.
        """
        content = request.content
        line_count = content.count(b"\n") + (0 if content.endswith(b"\n") else 1)
        end_line = max(1, min(root.end_point[0] + 1, line_count))
        qualified_name = module_path or PurePosixPath(request.relative_path).stem
        name = qualified_name.rsplit(".", 1)[-1]
        content_hash = hashlib.sha256(content).hexdigest()
        logical_id = symbol_id(
            request.repository_id,
            request.relative_path,
            qualified_name,
            SymbolKind.MODULE.value,
        )
        return SymbolRecord(
            symbol_id=logical_id,
            symbol_version_id=symbol_version_id(
                logical_id, content_hash, PARSER_BUNDLE_VERSION
            ),
            file_id=request.file_id,
            kind=SymbolKind.MODULE,
            name=name,
            qualified_name=qualified_name,
            module_path=module_path,
            signature=None,
            start_line=1,
            end_line=end_line,
            start_byte=0,
            end_byte=len(content),
            content_hash=content_hash,
            visibility="public",
        )

    def definitions_with_discriminators(
        self, request: ParseRequest
    ) -> list[tuple[SymbolRecord, str | None]]:
        """Each definition with the discriminator that separates it.

        Exists for `scripts/report_symbol_collisions.py`, which has to answer
        "is this group separated by something position-independent?" and cannot,
        from `parse` alone: `ensure_unique_symbol_ids` has already made every id
        distinct by the time a `ParseResult` is returned, so a census built on
        that output agrees with any fix, including a broken one.

        Ids are deliberately **pre-disambiguation** here. The census groups on
        qualified name and kind, and needs the discriminator beside them.
        """
        if not request.content or len(request.content) > MAX_PARSE_BYTES:
            return []
        tree = self._parser.parse(request.content)
        module_path = self._adapter.module_path(
            tree.root_node, request.content, request.relative_path
        )
        return self._definitions(tree.root_node, request, module_path)

    def _definitions(
        self, root: Any, request: ParseRequest, module_path: str
    ) -> list[tuple[SymbolRecord, str | None]]:
        """One SymbolRecord, and its discriminator, per matched definition.

        ``matches`` rather than ``captures``: a capture mapping is flat and
        carries no association between a definition and its name, which is
        exactly the pairing this needs.
        """
        # A span may match more than one definition pattern. Rust's tags.scm
        # matches a method inside an `impl` as BOTH `definition.method` (via the
        # enclosing declaration_list) and `definition.function` (the bare
        # function_item), and `kind` is part of `symbol_id`, so keeping both
        # would store two symbols for one function. The winner is whichever
        # capture appears EARLIER in `kind_by_capture`: that mapping's order
        # declares specificity, most specific first.
        rank_of = {
            name: rank for rank, name in enumerate(self._profile.kind_by_capture)
        }
        best: dict[tuple[int, int], tuple[int, SymbolRecord, str | None]] = {}
        for _pattern, captures in QueryCursor(self._profile.tags_query).matches(root):
            kind: SymbolKind | None = None
            definition_node: Any = None
            rank = len(rank_of)
            for capture_name, nodes in captures.items():
                if capture_name in self._profile.kind_by_capture and nodes:
                    kind = self._profile.kind_by_capture[capture_name]
                    definition_node = nodes[0]
                    rank = rank_of[capture_name]
            name_nodes = captures.get("name") or ()
            if kind is None or definition_node is None or not name_nodes:
                continue
            name = self._text(name_nodes[0], request.content)
            # Ask the adapter for an owner first. Go's receiver is a *field* of
            # the method node, not an ancestor, so lexical scope is the wrong
            # answer there and this hook is the reason the design is not purely
            # declarative (ADR-0065).
            owner = self._adapter.owner_hint(definition_node, request.content)
            scopes = (
                [owner] if owner else self._scopes(definition_node, request.content)
            )
            qualified_name = self._adapter.qualified_name(
                definition_node, name, scopes, request.content
            )
            span = (definition_node.start_byte, definition_node.end_byte)
            existing = best.get(span)
            if existing is not None and existing[0] <= rank:
                continue
            best[span] = (
                rank,
                self._record(
                    definition_node, request, kind, name, qualified_name, module_path
                ),
                self._adapter.discriminator(definition_node, request.content),
            )
        return [
            (record, discriminator)
            for _rank, record, discriminator in best.values()
        ]

    def _scopes(self, node: Any, source: bytes) -> list[str]:
        """Enclosing scope names, outermost first."""
        names: list[str] = []
        current = node.parent
        while current is not None:
            if current.type in self._profile.scope_node_types:
                named = current.child_by_field_name("name")
                if named is not None:
                    names.append(self._text(named, source))
            current = current.parent
        return list(reversed(names))

    def _record(
        self,
        node: Any,
        request: ParseRequest,
        kind: SymbolKind,
        name: str,
        qualified_name: str,
        module_path: str,
    ) -> SymbolRecord:
        definition_bytes = request.content[node.start_byte : node.end_byte]
        content_hash = hashlib.sha256(definition_bytes).hexdigest()
        logical_id = symbol_id(
            request.repository_id, request.relative_path, qualified_name, kind.value
        )
        return SymbolRecord(
            symbol_id=logical_id,
            symbol_version_id=symbol_version_id(
                logical_id, content_hash, PARSER_BUNDLE_VERSION
            ),
            file_id=request.file_id,
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            module_path=module_path,
            signature=self._adapter.signature(node, request.content),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            content_hash=content_hash,
            visibility=self._adapter.visibility(node, name, request.content),
        )

    @staticmethod
    def _text(node: Any, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", "replace")

    def _empty(self) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            symbols=(),
            diagnostics=(),
        )

    def _failed(self, diagnostic: ParseDiagnostic) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=False,
            symbols=(),
            diagnostics=(diagnostic,),
        )
