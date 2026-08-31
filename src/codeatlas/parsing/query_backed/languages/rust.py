"""Rust adapter: the parts of Rust that no query can express.

Rust needs `owner_hint` for a different reason than Go. A method *is* lexically
inside its `impl` block, but the owning type sits on the `impl_item`'s **`type`
field**, not its `name` field -- `impl_item` has no `name` field at all -- so the
engine's generic scope walk, which reads `child_by_field_name("name")`, would
find nothing and leave the method unqualified.

Unlike Go, Rust's module prefix is a **language keyword**. `crate`, `self` and
`super` are defined by the language rather than by external configuration, so
they can be stripped from a `use` path without guessing.

Nothing is compiled, expanded, or resolved through Cargo. A macro is recorded as
written; `Cargo.toml` is never read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Any

import tree_sitter_rust
from tree_sitter import Language, Query, QueryCursor

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility
from codeatlas.parsing.query_backed.profile import LanguageProfile
from codeatlas.parsing.query_backed.queries import load_query_source, load_tags_source

# Order declares specificity, most specific first: the engine keeps the
# earliest-ranked capture when two patterns match the same span. Rust's
# tags.scm matches a method inside an `impl` as both `definition.method` and
# `definition.function`, so `definition.method` must come first or every method
# would also be stored as a free function.
_KIND_BY_CAPTURE = {
    "definition.method": SymbolKind.METHOD,
    "definition.interface": SymbolKind.INTERFACE,
    "definition.class": SymbolKind.CLASS,
    "definition.module": SymbolKind.MODULE,
    "definition.macro": SymbolKind.FUNCTION,
    "definition.function": SymbolKind.FUNCTION,
}

# Path prefixes Rust defines itself. Stripping them is safe in a way Go's
# go.mod prefix never is, because these are keywords rather than configuration.
_PATH_KEYWORDS = frozenset({"crate", "self", "super"})


class RustAdapter:
    """Module paths, impl owners, `use` imports, and visibility for Rust."""

    def __init__(self) -> None:
        grammar = Language(tree_sitter_rust.language())
        self.profile = LanguageProfile(
            language="rust",
            grammar=grammar,
            tags_query=Query(grammar, load_tags_source("tree_sitter_rust")),
            imports_query=Query(grammar, load_query_source("rust.imports.scm")),
            kind_by_capture=_KIND_BY_CAPTURE,
            # `mod_item` is a real lexical scope; `impl_item` is handled by
            # `owner_hint` because its owner is on the `type` field.
            scope_node_types=frozenset({"mod_item"}),
        )

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        """The file's path, dotted. A Rust module is its file."""
        path = PurePosixPath(relative_path)
        stem = path.stem
        # `payments/mod.rs` is the module `payments`, not `payments.mod`.
        parts = [*path.parent.parts] if stem == "mod" else [*path.parent.parts, stem]
        return ".".join(parts)

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        return ".".join([*scopes, name]) if scopes else name

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        """The type of the enclosing `impl`, which is a field rather than a name."""
        current = node.parent
        while current is not None:
            if current.type == "impl_item":
                owner = current.child_by_field_name("type")
                return _text(owner, source) if owner is not None else None
            current = current.parent
        return None

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        """One IMPORTS reference per `use` path. Nothing is resolved here."""
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            statements = captures.get("import.statement", ())
            paths = captures.get("import.path", ())
            if not statements or not paths:
                continue
            for path in paths:
                segments = [
                    segment
                    for segment in _text(path, source).split("::")
                    if segment and segment not in _PATH_KEYWORDS
                ]
                if not segments:
                    continue
                # `use a::b::C` binds `C` (ADR-0039). The rest is the module.
                yield SymbolReference(
                    source_symbol_id=module_symbol_id,
                    file_id=file_id,
                    kind=RelationKind.IMPORTS,
                    target_hint=segments[-1],
                    module_hint=".".join(segments[:-1]),
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
        for child in node.children:
            if child.type == "visibility_modifier":
                return "public"
        return "private"


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")
