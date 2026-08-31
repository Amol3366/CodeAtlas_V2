"""Go adapter: the parts of Go that no query can express.

Go is the language that made a purely declarative design impossible (ADR-0065).
A method's owner is its **receiver**, which is a *field* of the method node
rather than a lexical ancestor, so `scope_node_types` is deliberately empty here
and `owner_hint` does the work. Walking ancestors would name the method `Audit`
with no owner -- a wrong qualified name rather than a missing one.

Nothing is imported, built, or resolved through the module cache. An import path
is untrusted text; it is recorded, never followed, and `go.mod` is never read --
a parse is a pure function of one file.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Any

import tree_sitter_go
from tree_sitter import Language, Query, QueryCursor

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility
from codeatlas.parsing.query_backed.profile import LanguageProfile
from codeatlas.parsing.query_backed.queries import load_query_source, load_tags_source

# `definition.type` covers both structs and interfaces: Go's tags.scm marks the
# `type_spec` generically, and its separate struct/interface patterns capture a
# bare `@name` with no definition capture to distinguish them. A Go interface is
# therefore reported as CLASS. Stated rather than worked around, because
# refining it would mean the engine inspecting a language-specific node type.
_KIND_BY_CAPTURE = {
    "definition.function": SymbolKind.FUNCTION,
    "definition.method": SymbolKind.METHOD,
    "definition.type": SymbolKind.CLASS,
}


class GoAdapter:
    """Module paths, receivers, imports, and visibility for Go."""

    def __init__(self) -> None:
        grammar = Language(tree_sitter_go.language())
        self.profile = LanguageProfile(
            language="go",
            grammar=grammar,
            tags_query=Query(grammar, load_tags_source("tree_sitter_go")),
            imports_query=Query(grammar, load_query_source("go.imports.scm")),
            kind_by_capture=_KIND_BY_CAPTURE,
            # Empty on purpose: a Go method is declared beside its type, not
            # inside it, so there is no lexical scope to walk. `owner_hint`
            # supplies the owner instead.
            scope_node_types=frozenset(),
        )

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        """The package's directory, dotted.

        Not the `package` clause: that is a short name (`payments`), while an
        import names a path (`myapp/internal/payments`). The directory is what
        the two have in common, and it is what `module_suffix_to_file` indexes.
        """
        directory = PurePosixPath(relative_path).parent
        return ".".join(directory.parts) if directory.parts else ""

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        return ".".join([*scopes, name]) if scopes else name

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        """The receiver's type, for a method. The measured case of ADR-0065."""
        receiver = node.child_by_field_name("receiver")
        if receiver is None:
            return None
        # `(s *OrderService)` -- the type identifier is nested under a pointer
        # or named type, so take the first type_identifier in the subtree.
        found = _first_of_type(receiver, "type_identifier")
        return _text(found, source) if found is not None else None

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        """One IMPORTS reference per import spec. Nothing is resolved here."""
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            statements = captures.get("import.statement", ())
            paths = captures.get("import.path", ())
            if not statements or not paths:
                continue
            for path in paths:
                quoted = _text(path, source)
                specifier = quoted.strip('"')
                if not specifier:
                    continue
                # `import "a/b/payments"` binds the identifier `payments`, so
                # IMPORTS targets the bound name (ADR-0039). The dotted path
                # travels as the module hint for the resolver's module lookup.
                bound = specifier.rsplit("/", 1)[-1]
                yield SymbolReference(
                    source_symbol_id=module_symbol_id,
                    file_id=file_id,
                    kind=RelationKind.IMPORTS,
                    target_hint=bound,
                    module_hint=specifier.replace("/", "."),
                    # The spec's own line, not the declaration's. A grouped
                    # import puts every path under one statement node, so
                    # using the statement made each path cite the opening
                    # line -- which does not contain the import -- and made
                    # two paths sharing a bound name collide on relation_id
                    # (`crypto/rand` and `math/rand` in gin, 2026-08-22).
                    start_line=path.start_point[0] + 1,
                    end_line=path.end_point[0] + 1,
                )

    def visibility(self, node: Any, name: str, source: bytes) -> Visibility:
        """Go's own rule: an identifier is exported iff it starts uppercase."""
        return "public" if name[:1].isupper() else "private"


def _first_of_type(node: Any, node_type: str) -> Any | None:
    stack = list(node.children)
    while stack:
        current = stack.pop(0)
        if current.type == node_type:
            return current
        stack.extend(current.children)
    return None


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")
