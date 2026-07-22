"""The Python language parser (Blueprint §4.4, Phase 3).

Primary path uses Python's ``ast`` for accurate symbols and relations. If the
source has a syntax error, it falls back to tree-sitter for partial symbol
recovery and records an ``error`` diagnostic — indexing of other files continues
(CLAUDE.md §14: diagnostics over crashes).
"""

from __future__ import annotations

from codeatlas.domain.enums import Language
from codeatlas.parsing.contracts import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)
from codeatlas.parsing.python.ast_extractor import PythonAstExtractor
from codeatlas.parsing.python.tree_sitter_fallback import extract_partial

PYTHON_PARSER_VERSION = PARSER_BUNDLE_VERSION


class PythonParser:
    """Parses Python source into stable symbols and relations."""

    name = "python"
    version = PYTHON_PARSER_VERSION
    supported_extensions = frozenset({".py", ".pyi"})

    def parse(self, request: ParseRequest) -> ParseResult:
        source_bytes = request.content
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError:
            source = source_bytes.decode("utf-8", errors="replace")

        try:
            extractor = PythonAstExtractor(request.repository_id, request.relative_path)
            symbols, relations = extractor.run(source)
        except SyntaxError as exc:
            return self._partial_result(request, source_bytes, exc)

        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            language=Language.PYTHON,
            relative_path=request.relative_path,
            success=True,
            symbols=tuple(symbols),
            relations=tuple(relations),
            diagnostics=(),
        )

    def _partial_result(
        self, request: ParseRequest, source_bytes: bytes, exc: SyntaxError
    ) -> ParseResult:
        diagnostic = ParseDiagnostic(
            severity="error",
            message="Python syntax error; recovered partial symbols via tree-sitter",
            line=exc.lineno,
            detail=str(exc.msg),
        )
        symbols = extract_partial(request.repository_id, request.relative_path, source_bytes)
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            language=Language.PYTHON,
            relative_path=request.relative_path,
            success=False,
            symbols=tuple(symbols),
            relations=(),
            diagnostics=(diagnostic,),
        )
