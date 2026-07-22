"""The JavaScript parser (Blueprint §4.4, Phase 4).

Tree-sitter based; handles ESM/CommonJS. Malformed sources never raise — a
diagnostic is recorded and best-effort symbols are returned.
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
from codeatlas.parsing.tree_sitter.loader import javascript_parser


class JavaScriptParser:
    name = "javascript"
    version = PARSER_BUNDLE_VERSION
    supported_extensions = frozenset({".js", ".jsx", ".mjs", ".cjs"})

    def parse(self, request: ParseRequest) -> ParseResult:
        symbols, relations, has_error = JsTsExtractor(
            request.repository_id, request.relative_path, Language.JAVASCRIPT
        ).run(javascript_parser(), request.content)
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
            language=Language.JAVASCRIPT,
            relative_path=request.relative_path,
            success=not has_error,
            symbols=tuple(symbols),
            relations=tuple(relations),
            diagnostics=diagnostics,
        )
