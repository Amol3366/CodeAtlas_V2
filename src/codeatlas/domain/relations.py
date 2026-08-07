"""Relations: what one file said, and what that turned out to mean.

Relation derivation is deliberately two stages, and the split is the reason this
module holds two types rather than one.

A :class:`SymbolReference` is what a single file states outright — ``total``,
``"./orders"``, ``Order``. Producing one is a pure function of that file's bytes,
so an unchanged file's references can be copied into a new snapshot untouched.

A :class:`RelationRecord` is what a reference resolved to *in a particular
snapshot*. That needs every file, so it is recomputed on every index run. Because
resolution never reuses a previous run's answer, an edge pointing at a symbol
that has since moved or vanished cannot survive into a new snapshot: the
guarantee holds by construction rather than by bookkeeping that can drift.

Unresolved is a first-class state, not a missing row. An import of ``react`` is a
real fact about a file even though no repository symbol answers it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from codeatlas.contracts import Derivation, RelationKind

# `module_hint` normally carries the receiver or module a reference was written
# against. These three values mark references that carry something else, and
# they live here because they are part of the reference vocabulary itself:
# extraction writes them, resolution reads them, and indexing depends on the
# last one. Each contains a character that cannot appear in an expression, so
# none can collide with a real receiver.
ROUTE_HINT: Final[str] = "<route>"
"""``target_hint`` is a normalized URL path, not a symbol name."""

MENTION_HINT: Final[str] = "<mention>"
"""``target_hint`` is a word a document used, not a symbol name."""

DERIVED_HINT: Final[str] = "<derived>"
"""The edge was combined from several references and must be re-derived."""

FIXTURE_HINT: Final[str] = "<fixture>"
"""A weak `TESTS` edge derived by following a `CONSUMES_FIXTURE` reference."""

HELPER_HINT: Final[str] = "<helper>"
"""A weak `TESTS` edge derived by following a test-helper call."""


@dataclass(frozen=True)
class StoredEvidence:
    """An evidence row: where to look and what the content hashed to.

    The excerpt is deliberately absent. Fetching re-reads the file and
    re-verifies this hash, so a stored row can never outlive the content it
    describes.
    """

    evidence_id: str
    file_id: str
    start_line: int
    end_line: int
    content_hash: str
    derivation: Derivation


class ResolutionState(StrEnum):
    """What resolution concluded about a reference's target."""

    RESOLVED = "resolved"
    """``target_symbol_id`` names a symbol in this snapshot."""

    EXTERNAL = "external"
    """The target is real but outside the repository, such as a package import."""

    UNRESOLVED = "unresolved"
    """The target could not be determined. Recorded so the gap stays visible."""

    AMBIGUOUS = "ambiguous"
    """More than one candidate matched. Every one is counted; none is chosen."""


@dataclass(frozen=True)
class SymbolReference:
    """What one file said, before anything else was consulted.

    ``target_hint`` is the name as written at the call or import site.
    ``module_hint`` carries the receiver or module when the syntax names one, and
    is empty otherwise. Neither is resolved here — that is the point.

    ``part`` distinguishes two references that are otherwise identical because
    they occur on the same line, as in ``f(f(x))``. Both are real edges.
    """

    source_symbol_id: str
    file_id: str
    kind: RelationKind
    target_hint: str
    module_hint: str
    start_line: int
    end_line: int
    part: int = 0


@dataclass(frozen=True)
class RelationRecord:
    """One resolved edge, snapshot-scoped and citable.

    ``target_symbol_id`` is ``None`` for every state except ``RESOLVED``. That is
    not a missing value: an external, unresolved, or ambiguous reference has no
    single symbol to name, and inventing one would turn a heuristic into an
    apparent fact.

    ``derivation`` and ``confidence`` stay separate fields, per ``CLAUDE.md``
    Section 11: how an edge was derived and how sure it is are different
    questions, and collapsing them lets a heuristic borrow authority it has not
    earned.
    """

    relation_id: str
    source_symbol_id: str
    target_symbol_id: str | None
    file_id: str
    kind: RelationKind
    target_hint: str
    resolution: ResolutionState
    derivation: Derivation
    confidence: float
    start_line: int
    end_line: int
    candidate_count: int
    # Carried so a relation round-trips back into the reference that produced
    # it. That is what lets an unchanged file's references be reused while its
    # targets are still re-resolved from scratch.
    module_hint: str = ""
    reference_part: int = 0

    @property
    def is_derived(self) -> bool:
        """Whether this edge was combined from several references.

        A derived edge cannot be turned back into the reference that stated it,
        because no single reference did. Indexing recomputes these rather than
        carrying them forward: the other references they were derived from may
        have changed even when this file did not.
        """
        return (
            self.kind is RelationKind.TESTS or self.module_hint == DERIVED_HINT
        )

    def as_reference(self) -> SymbolReference:
        """Recover the reference this relation was resolved from."""
        return SymbolReference(
            source_symbol_id=self.source_symbol_id,
            file_id=self.file_id,
            kind=_stated_kind(self.kind, self.module_hint),
            target_hint=self.target_hint,
            module_hint=self.module_hint,
            start_line=self.start_line,
            end_line=self.end_line,
            part=self.reference_part,
        )


def _stated_kind(kind: RelationKind, module_hint: str) -> RelationKind:
    """The kind the *file* stated, undoing what resolution concluded.

    Two kinds are resolution outcomes rather than syntax. ``MAY_CALL`` is what an
    ambiguous call becomes, and a route literal held in a constant becomes
    ``REFERENCES`` because a constant calls nothing. Both must round-trip to what
    was written, or re-resolving a reused file would resolve a different fact.
    """
    if kind is RelationKind.MAY_CALL:
        return RelationKind.CALLS
    if kind is RelationKind.REFERENCES and module_hint == ROUTE_HINT:
        return RelationKind.ROUTES_TO
    return kind
