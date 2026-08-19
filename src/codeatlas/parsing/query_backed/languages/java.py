"""Java adapter: the parts of Java that no query can express.

What Tree-sitter cannot see, this parser does not claim to know. There is no
`javac` in the loop -- running one would execute repository tooling, which
``AGENTS.md`` section 4.4 forbids -- so inferred generics, resolved classpaths,
and annotation processors are outside what any edge here asserts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Any

import tree_sitter_java
from tree_sitter import Language, Query, QueryCursor

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility
from codeatlas.parsing.query_backed.profile import LanguageProfile
from codeatlas.parsing.query_backed.queries import load_query_source, load_tags_source

_KIND_BY_CAPTURE = {
    "definition.class": SymbolKind.CLASS,
    "definition.interface": SymbolKind.INTERFACE,
    "definition.method": SymbolKind.METHOD,
}

_SCOPE_NODE_TYPES = frozenset(
    {"class_declaration", "interface_declaration", "enum_declaration"}
)


class JavaAdapter:
    """Module paths, qualified names, imports, and visibility for Java."""

    def __init__(self) -> None:
        grammar = Language(tree_sitter_java.language())
        self.profile = LanguageProfile(
            language="java",
            grammar=grammar,
            tags_query=Query(grammar, load_tags_source("tree_sitter_java")),
            imports_query=Query(grammar, load_query_source("java.imports.scm")),
            kind_by_capture=_KIND_BY_CAPTURE,
            scope_node_types=_SCOPE_NODE_TYPES,
        )

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        """The declared package, or the path when a file declares none."""
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            for node in captures.get("package.name", ()):
                return _text(node, source)
        # A file with no package declaration is in the default package. Falling
        # back to the path keeps module_path non-empty, which snapshot
        # validation requires, and keeps it stable across edits.
        path = PurePosixPath(relative_path)
        return ".".join([*path.parent.parts, path.stem])

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        return ".".join([*scopes, name]) if scopes else name

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        # Java owners are lexical ancestors, so scope walking already has them.
        return None

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        """One IMPORTS reference per import declaration. Nothing is resolved."""
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            statements = captures.get("import.statement", ())
            paths = captures.get("import.path", ())
            if not statements or not paths:
                continue
            statement, path = statements[0], paths[0]
            dotted = _text(path, source)
            # `import a.b.C` binds `C`, so IMPORTS targets the bound symbol
            # rather than the package -- ADR-0039's rule, applied to Java.
            bound = dotted.rsplit(".", 1)[-1]
            yield SymbolReference(
                source_symbol_id=module_symbol_id,
                file_id=file_id,
                kind=RelationKind.IMPORTS,
                target_hint=bound,
                module_hint=dotted.rsplit(".", 1)[0] if "." in dotted else "",
                start_line=statement.start_point[0] + 1,
                end_line=statement.end_point[0] + 1,
            )

    def visibility(self, node: Any, name: str, source: bytes) -> Visibility:
        for child in node.children:
            if child.type == "modifiers" and b"public" in source[
                child.start_byte : child.end_byte
            ]:
                return "public"
        return "private"


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")
