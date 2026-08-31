"""Scala adapter: the parts of Scala that no query can express.

Scala is the Java-shaped case. Its module is a declared `package`, and a member
is owned by the lexically enclosing class, object, or trait -- so unlike Go and
Rust it needs no `owner_hint` at all, and the engine's generic scope walk does
the work. That the same engine covers both shapes is the point of the design.

Nothing is compiled or resolved through sbt or Coursier. `build.sbt` is never
read, and an import path is untrusted text.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Any

import tree_sitter_scala
from tree_sitter import Language, Query, QueryCursor

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility
from codeatlas.parsing.query_backed.profile import LanguageProfile
from codeatlas.parsing.query_backed.queries import load_query_source, load_tags_source

# Order declares specificity, most specific first (see the engine's span
# deduplication). `definition.module` is deliberately absent: Scala's tags.scm
# marks the `package_clause` as one, but the package is this file's *module
# path*, not a symbol defined in it, and storing it as a symbol would make every
# file define a symbol named after its own package.
_KIND_BY_CAPTURE = {
    "definition.interface": SymbolKind.INTERFACE,
    "definition.enum": SymbolKind.ENUM,
    "definition.object": SymbolKind.CLASS,
    "definition.class": SymbolKind.CLASS,
    "definition.type": SymbolKind.TYPE_ALIAS,
    "definition.function": SymbolKind.FUNCTION,
    "definition.property": SymbolKind.PROPERTY,
    "definition.variable": SymbolKind.FIELD,
}

_SCOPE_NODE_TYPES = frozenset(
    {
        "class_definition",
        "object_definition",
        "trait_definition",
        "enum_definition",
    }
)


_ENCLOSING_FORMS = frozenset(
    {"class_definition", "trait_definition", "object_definition"}
)

class ScalaAdapter:
    """Package paths, imports, and visibility for Scala."""

    def __init__(self) -> None:
        grammar = Language(tree_sitter_scala.language())
        self.profile = LanguageProfile(
            language="scala",
            grammar=grammar,
            tags_query=Query(grammar, load_tags_source("tree_sitter_scala")),
            imports_query=Query(grammar, load_query_source("scala.imports.scm")),
            kind_by_capture=_KIND_BY_CAPTURE,
            scope_node_types=_SCOPE_NODE_TYPES,
            # Scala is the only one of the four whose shipped `tags.scm` has no
            # member-call pattern, so `payments.charge(id)` produced no edge
            # (ADR-0065 recorded it; ADR-0067 closes it). Java, Go and Rust
            # supply nothing here and are unaffected.
            references_query=Query(
                grammar, load_query_source("scala.references.scm")
            ),
        )

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        """The declared package, or the path when a file declares none."""
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            for node in captures.get("package.name", ()):
                return _text(node, source)
        path = PurePosixPath(relative_path)
        return ".".join([*path.parent.parts, path.stem])

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        return ".".join([*scopes, name]) if scopes else name

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        # Scala owners are lexical ancestors, as in Java. No hook needed.
        return None

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        """One IMPORTS reference per import statement. Nothing is resolved here."""
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            for statement in captures.get("import.statement", ()):
                text = _text(statement, source)
                dotted = text.removeprefix("import").strip()
                # A selector import (`import a.b.{C, D}`) names several symbols;
                # the brace group is recorded as the module rather than guessed
                # apart, because picking one member would misstate the others.
                if not dotted or "{" in dotted or dotted.endswith("_"):
                    continue
                segments = [part for part in dotted.split(".") if part]
                if not segments:
                    continue
                # `import a.b.C` binds `C` (ADR-0039).
                yield SymbolReference(
                    source_symbol_id=module_symbol_id,
                    file_id=file_id,
                    kind=RelationKind.IMPORTS,
                    target_hint=segments[-1],
                    module_hint=".".join(segments[:-1]),
                    start_line=statement.start_point[0] + 1,
                    end_line=statement.end_point[0] + 1,
                )

    def signature(self, node: Any, source: bytes) -> str | None:
        """The method's parameter types, comma-joined per parameter list.

        Scala overloads collide exactly as Java's do and are separated the same
        way. **Companion `trait`/`object` pairs are not** -- neither declares
        parameters, so both yield None and fall back to the ordinal. That is
        the larger share of scalaz's 2204 collisions and it is measured, not
        assumed (ADR-0071).

        Every parameter list is collected, not just the first: `def f(a: Int)(b: Int)`
        declares two, and taking one would make the two halves of a curried
        overload pair look identical.
        """
        lists = [
            child for child in node.named_children if child.type == "parameters"
        ]
        if not lists:
            return None
        rendered: list[str] = []
        for parameters in lists:
            types: list[str] = []
            for child in parameters.named_children:
                declared = child.child_by_field_name("type")
                if declared is None:
                    continue
                types.append(_text(declared, source))
            rendered.append("(" + ",".join(types) + ")")
        return "".join(rendered)


    def discriminator(self, node: Any, source: bytes) -> str | None:
        """A declaration form: the symbol's own if it has one, else its parent's.

        A `trait` and its companion `object` render the same qualified-name
        prefix, so `Align.max` declared in both collides on name and kind while
        neither declares a parameter. The *parents* do not collide -- a trait is
        an INTERFACE and an object is a CLASS -- which is where ADR-0071 went
        wrong. 772 of the 981 groups it left on the ordinal are these members
        (ADR-0072).

        The form, not the name: the name is already in the qualified name, and
        the form is what actually differs between the two parents.
        """
        if node.type in _ENCLOSING_FORMS:
            # A parent's OWN form. `class Align` and `object Align` both map to
            # CLASS and collide at top level, where there is no enclosing
            # declaration at all -- 114 of scalaz's groups, measured. A `trait`
            # maps to INTERFACE and never collided with either, which is the
            # pair ADR-0071 named and ADR-0072 corrected.
            return str(node.type).removesuffix("_definition")
        current = node.parent
        while current is not None:
            if current.type in _ENCLOSING_FORMS:
                return str(current.type).removesuffix("_definition")
            current = current.parent
        return None

    def visibility(self, node: Any, name: str, source: bytes) -> Visibility:
        """Scala is public by default; only an explicit modifier narrows it."""
        for child in node.children:
            if child.type == "modifiers":
                text = source[child.start_byte : child.end_byte]
                if b"private" in text or b"protected" in text:
                    return "private"
        return "public"


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")
