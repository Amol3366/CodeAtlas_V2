"""The TypeScript parser (Blueprint §4.4, Phase 4).

Tree-sitter based (the TypeScript compiler API is a deferred, evaluation-gated
follow-up — CLAUDE.md §Phase 4). Malformed sources never raise: tree-sitter
still yields a (partial) tree, and a diagnostic is recorded.
"""

from __future__ import annotations

from codeatlas.domain.enums import Language
from codeatlas.parsing.contracts import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)
from codeatlas.parsing.tree_sitter.js_ts_extractor import JsTsExtractor
from codeatlas.parsing.tree_sitter.loader import tsx_parser, typescript_parser


class TypeScriptParser:
    name = "typescript"
    version = PARSER_BUNDLE_VERSION
    supported_extensions = frozenset({".ts", ".tsx"})

    def parse(self, request: ParseRequest) -> ParseResult:
        parser = tsx_parser() if request.relative_path.endswith(".tsx") else typescript_parser()
        symbols, relations, has_error = JsTsExtractor(
            request.repository_id, request.relative_path, Language.TYPESCRIPT
        ).run(parser, request.content)
        diagnostics = (
            (
                ParseDiagnostic(
                    severity="warning",
                    message="Syntax errors present; symbols extracted best-effort",
                ),
            )
            if has_error
            else ()
        )
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            language=Language.TYPESCRIPT,
            relative_path=request.relative_path,
            success=not has_error,
            symbols=tuple(symbols),
            relations=tuple(relations),
            diagnostics=diagnostics,
        )
