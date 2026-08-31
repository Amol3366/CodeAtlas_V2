"""Contracts for query-backed language support.

A profile is the data a language contributes; an adapter is the small amount of
behavior a language needs that no query can express. The split is not
stylistic: measurement on 2026-08-19 showed Go's method receiver is a *field* of
the method node rather than a lexical ancestor, so a purely declarative design
produces a wrong qualified name rather than a missing one (ADR-0065).

Nor can a query supply imports. No shipped ``tags.scm`` captures one, across all
nine grammars that ship a ``tags.scm`` at all -- which matters because
resolution is built on the import graph. ``LanguageAdapter.imports`` is where
that gap is filled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from codeatlas.contracts import SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility


@dataclass(frozen=True)
class LanguageProfile:
    """Everything a language contributes as data rather than as behavior.

    ``grammar``, ``tags_query``, ``imports_query`` and ``references_query`` are
    typed ``Any`` because they are Tree-sitter objects: importing ``tree_sitter``
    types here would put a parser dependency in a contract module that adapters
    and tests both read.
    """

    language: str
    grammar: Any
    tags_query: Any
    imports_query: Any
    kind_by_capture: Mapping[str, SymbolKind]
    scope_node_types: frozenset[str]
    # An optional second authored query, for references a grammar's shipped
    # `tags.scm` does not capture (ADR-0067).
    #
    # It exists because Scala's `tags.scm` matches only
    # `(call_expression (identifier) @name)`, so `payments.charge(id)` -- most
    # real Scala calls -- produced no edge at all, while Java, Go and Rust all
    # ship a member-call pattern. ADR-0065 declined to widen the contract
    # mid-slice and recorded the gap instead; this is that gap closed.
    #
    # **Optional on purpose.** A language whose shipped query is sufficient
    # supplies nothing and runs exactly as before, so adding the slot changed no
    # behaviour for Java, Go or Rust. Its captures use the same
    # `reference.*` / `@name` convention as `tags_query`, which is what lets one
    # extractor consume both without knowing which query a match came from.
    references_query: Any | None = None


class LanguageAdapter(Protocol):
    """The behavior a language needs that no query can express."""

    profile: LanguageProfile

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        """The module or package this file declares, dotted."""
        ...

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        """The symbol's fully qualified name within its module."""
        ...

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        """The type owning this definition when it is not a lexical ancestor.

        Returning ``None`` means "use lexical scope", which is correct for Java
        and Scala. Go returns the receiver type here, because its methods are
        declared beside the type rather than inside it.
        """
        ...

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        """IMPORTS references this file declares. Never resolved here."""
        ...

    def visibility(self, node: Any, name: str, source: bytes) -> Visibility:
        """Whether the symbol is visible outside its module."""
        ...

    def signature(self, node: Any, source: bytes) -> str | None:
        """The parameter types this definition declares, or ``None``.

        Feeds symbol identity: ``ensure_unique_symbol_ids`` disambiguates a
        collision group by signature first and by ordinal only when signatures
        match, so a language that supplies one gets identity that survives a
        same-named sibling being inserted above it (ADR-0069, ADR-0071).

        **Types only, never parameter names.** A rename must not change
        identity, and including names would make a renamed parameter look like
        a deleted symbol and a new one.

        Returning ``None`` is correct wherever a signature cannot separate the
        collisions the language actually produces -- Go and Rust, measured, do
        that. See ADR-0071.
        """
        ...
