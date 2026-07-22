"""Parser registry with extension dispatch (Blueprint §4.4.1).

Maps file extensions to a :class:`LanguageParser`. Phase 3 registers only the
Python parser; later phases add TypeScript/JavaScript/Markdown/config parsers.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from codeatlas.parsing.contracts import LanguageParser
from codeatlas.parsing.javascript.parser import JavaScriptParser
from codeatlas.parsing.python.parser import PythonParser
from codeatlas.parsing.typescript.parser import TypeScriptParser


class ParserRegistry:
    def __init__(self) -> None:
        self._by_extension: dict[str, LanguageParser] = {}

    def register(self, parser: LanguageParser) -> None:
        for extension in parser.supported_extensions:
            self._by_extension[extension.lower()] = parser

    def for_extension(self, extension: str) -> LanguageParser | None:
        return self._by_extension.get(extension.lower())

    def for_path(self, relative_path: str) -> LanguageParser | None:
        return self.for_extension(PurePosixPath(relative_path).suffix)


def default_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(PythonParser())
    registry.register(TypeScriptParser())
    registry.register(JavaScriptParser())
    return registry
