"""The finding rule table: what a change is, stated once per symbol.

Findings are minimal on purpose. Finding precision is a release gate, so a rule
fires only when its conditions prove what its code says, and an observation that
cannot be proven belongs in the report's limitations rather than in a finding.

The structure is one *primary* finding per changed symbol, chosen by the first
matching rule in a fixed order, plus a small number of independent rules that
describe something the primary cannot: a file that was renamed, a document that
should be re-read, an architecture rule that a new edge broke.

The order is not arbitrary. It runs from "this symbol is gone" through "this is
what kind of artifact it is" to "this is what changed inside it", because the
first true statement in that sequence is the one a reviewer needs. A deleted
symbol's body diff is not interesting; a changed test is a changed test before
it is a changed function.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from codeatlas.analysis.impact import GraphSide
from codeatlas.contracts import (
    AnalysisSide,
    ChangeKind,
    Derivation,
    FileChangeKind,
    RelationKind,
    Severity,
    SymbolKind,
)
from codeatlas.domain.change import (
    BodyChangeClass,
    FileChange,
    SignatureChangeClass,
    SymbolChange,
)
from codeatlas.domain.relations import ROUTE_HINT, RelationRecord, ResolutionState

# Phrases that mark repository prose attempting to instruct a reader or a model.
# The list is short and literal on purpose: it exists to *label* content as
# untrusted, never to decide whether the content is dangerous, and a clever
# rewording evading it costs nothing because the content was already data.
_INJECTION_MARKERS: Final[tuple[str, ...]] = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "reveal all secrets",
    "upload every source file",
    "you are now",
    "system prompt",
)

_TYPE_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.INTERFACE, SymbolKind.TYPE_ALIAS, SymbolKind.ENUM}
)

_TEST_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.TEST, SymbolKind.FIXTURE}
)

_VALUE_KINDS: Final[frozenset[SymbolKind]] = frozenset(
    {SymbolKind.CONSTANT, SymbolKind.PROPERTY, SymbolKind.FIELD}
)

_SEVERITY_RANK: Final[dict[Severity, int]] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


@dataclass(frozen=True)
class FindingDraft:
    """A finding before its evidence exists.

    The rule table names *what* a finding cites — a symbol, or a file pair — and
    the engine turns that into a hash-verified evidence row. Keeping the two
    apart means a rule can be tested without a repository on disk.
    """

    code: str
    severity: Severity
    title: str
    description: str
    derivation: Derivation
    confidence: float
    subject: str
    # The file the subject lives in, for symbol drafts. A qualified name is not
    # unique across a repository -- two modules may each define `total` -- so a
    # subject alone cannot identify which changed symbol this draft is about,
    # and the citation step resolved both to whichever one it saw last
    # (ADR-0054). `None` for file-level and architecture drafts, whose subject is
    # already a path or a rule source.
    #
    # This is ADR-0042's rule reaching a surface it did not: pair within the
    # file first.
    subject_file: str | None = None
    side: AnalysisSide = AnalysisSide.TARGET
    remediation: str | None = None
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rule_id: str | None = None


@dataclass(frozen=True)
class ArchitectureViolation:
    """One forbidden edge that the target state introduced."""

    rule_id: str
    severity: Severity
    source: str
    target: str
    kind: RelationKind
    description: str


@dataclass
class _Graphs:
    """The edge facts the rules ask about, indexed once."""

    inbound: dict[str, list[RelationRecord]] = field(default_factory=dict)
    outbound: dict[str, list[RelationRecord]] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, side: GraphSide) -> _Graphs:
        built = cls()
        for symbol_id in sorted(side.symbols):
            built.ids.setdefault(side.symbols[symbol_id].qualified_name, symbol_id)
        for relation in side.relations:
            if relation.resolution is not ResolutionState.RESOLVED:
                continue
            target = relation.target_symbol_id
            if target is None:
                continue
            built.outbound.setdefault(relation.source_symbol_id, []).append(relation)
            built.inbound.setdefault(target, []).append(relation)
        return built

    def has_inbound(self, name: str, kind: RelationKind) -> bool:
        symbol_id = self.ids.get(name)
        if symbol_id is None:
            return False
        return any(
            relation.kind is kind for relation in self.inbound.get(symbol_id, ())
        )

    def has_outbound(self, name: str, kind: RelationKind) -> bool:
        symbol_id = self.ids.get(name)
        if symbol_id is None:
            return False
        return any(
            relation.kind is kind for relation in self.outbound.get(symbol_id, ())
        )

    def has_outbound_route_reference(self, name: str) -> bool:
        """A constant holding a path resolves to `REFERENCES`, not `ROUTES_TO`."""
        symbol_id = self.ids.get(name)
        if symbol_id is None:
            return False
        return any(
            relation.kind is RelationKind.REFERENCES
            and relation.module_hint == ROUTE_HINT
            for relation in self.outbound.get(symbol_id, ())
        )


def evaluate_findings(
    changes: Sequence[SymbolChange],
    *,
    files: Sequence[FileChange] = (),
    base: GraphSide,
    target: GraphSide,
    document_text: Mapping[str, str] | None = None,
    violations: Sequence[ArchitectureViolation] = (),
) -> tuple[FindingDraft, ...]:
    """Apply the rule table to one change set."""
    base_graph = _Graphs.build(base)
    target_graph = _Graphs.build(target)
    text = document_text or {}
    renamed: set[str] = set()
    for entry in files:
        if entry.kind is not FileChangeKind.RENAMED:
            continue
        renamed.add(entry.path)
        if entry.base_path:
            renamed.add(entry.base_path)

    drafts: list[FindingDraft] = [
        _renamed_file(change) for change in files
        if change.kind is FileChangeKind.RENAMED
    ]

    for change in sorted(changes, key=lambda item: item.qualified_name):
        primary = _primary(
            change,
            base_graph=base_graph,
            target_graph=target_graph,
            text=text,
            renamed=renamed,
        )
        if primary is not None:
            drafts.append(primary)
        drafts.extend(_independent(change, target_graph=target_graph))

    drafts.extend(_architecture(violations))
    return tuple(drafts)


def _primary(
    change: SymbolChange,
    *,
    base_graph: _Graphs,
    target_graph: _Graphs,
    text: Mapping[str, str],
    renamed: set[str],
) -> FindingDraft | None:
    """The one finding that best describes this symbol's change."""
    name = change.qualified_name

    if change.change_kind is ChangeKind.DELETED:
        return _draft(
            "SYMBOL_DELETED",
            Severity.HIGH,
            f"{name} was deleted",
            f"{name} no longer exists in the target state. Any reference to it "
            "resolves to nothing.",
            Derivation.DETERMINISTIC,
            change,
            side=AnalysisSide.BASE,
            remediation="Remove or redirect the references this deletion orphans.",
        )

    if change.change_kind is ChangeKind.MOVED and change.file_path not in renamed:
        # A move inside a renamed file is already reported as the rename; saying
        # it twice would double-count one fact.
        return _draft(
            "SYMBOL_MOVED",
            Severity.MEDIUM,
            f"{name} moved to another file",
            f"{name} was found in exactly one other file, so its identity is "
            "carried across rather than reported as a delete and an add.",
            Derivation.DETERMINISTIC,
            change,
        )

    classification = _classification(change, text)
    if classification is not None:
        return classification

    association = _association(change, target_graph)
    if association is not None:
        return association

    if change.change_kind is ChangeKind.DEPENDENCY:
        return _draft(
            "DEPENDENCY_CHANGED",
            Severity.MEDIUM,
            f"{name} depends on something new",
            f"The body of {name} is unchanged, but the set of symbols its "
            "references resolve to is not.",
            Derivation.DETERMINISTIC,
            change,
        )

    if change.change_kind is ChangeKind.ADDED:
        return _draft(
            "SYMBOL_ADDED",
            Severity.INFO,
            f"{name} was added",
            f"{name} exists in the target state and not in the base state.",
            Derivation.DETERMINISTIC,
            change,
        )

    export = _export(change, base_graph, target_graph)
    if export is not None:
        return export

    if change.symbol_kind in _TYPE_KINDS:
        # A type's body *is* its shape: whether the diff landed in the
        # signature string or in a member line, every user of the type sees
        # the same contract change (c007).
        return _draft(
            "PUBLIC_TYPE_CHANGED",
            Severity.HIGH,
            f"The shape of {change.qualified_name} changed",
            f"{change.qualified_name} declares a different shape in the "
            "target state. Every user of the type sees the change.",
            Derivation.DETERMINISTIC,
            change,
        )

    signature = _signature(change)
    if signature is not None:
        return signature

    return _body(change, target_graph)


def _classification(
    change: SymbolChange, text: Mapping[str, str]
) -> FindingDraft | None:
    """What kind of artifact changed, which outranks what changed inside it.

    Order matters within this group. A `package.json` script is a configuration
    value, and a document carrying injection markers is a document; in both
    cases the narrower rule is the one a reviewer needs, so it fires and the
    broader one does not.
    """
    name = change.qualified_name

    if change.symbol_kind is SymbolKind.DOCUMENT_SECTION and _is_injection(
        text.get(name, "")
    ):
        return _draft(
            "UNTRUSTED_CONTENT_CHANGED",
            Severity.LOW,
            f"{name} changed and reads as an instruction",
            "The changed document text matches a known instruction pattern. "
            "Repository content is data and is never executed or obeyed.",
            Derivation.DETERMINISTIC,
            change,
            warnings=("REPOSITORY_CONTENT_IS_DATA",),
            limitations=(
                "Matching an instruction pattern is not evidence of intent.",
            ),
        )

    if change.symbol_kind is SymbolKind.CONFIG_KEY and _is_package_script(change):
        return _draft(
            "PACKAGE_SCRIPT_CHANGED",
            Severity.MEDIUM,
            f"{name} changed in package.json",
            "A package script changed. CodeAtlas reads scripts as data and "
            "never runs them, so their effect is not known here.",
            Derivation.DETERMINISTIC,
            change,
            warnings=("PACKAGE_SCRIPTS_NOT_EXECUTED",),
        )

    if change.symbol_kind is SymbolKind.CONFIG_KEY:
        return _draft(
            "CONFIG_VALUE_CHANGED",
            Severity.MEDIUM,
            f"{name} changed",
            f"The configuration key {name} holds a different value in the "
            "target state.",
            Derivation.DETERMINISTIC,
            change,
        )

    if change.symbol_kind is SymbolKind.DOCUMENT_SECTION:
        return _draft(
            "DOCUMENT_CHANGED",
            Severity.INFO,
            f"{name} changed",
            f"The document section {name} differs between the two states.",
            Derivation.DETERMINISTIC,
            change,
        )

    if change.symbol_kind in _TEST_KINDS:
        return _draft(
            "TEST_CHANGED",
            Severity.INFO,
            f"{name} changed",
            f"The test {name} differs between the two states. Whether it passes "
            "is not known: CodeAtlas does not execute tests.",
            Derivation.DETERMINISTIC,
            change,
            limitations=("Test execution is outside CodeAtlas's scope.",),
        )
    return None


def _association(change: SymbolChange, target: _Graphs) -> FindingDraft | None:
    """A change to one end of a path agreement, which the other end may rely on."""
    name = change.qualified_name

    if target.has_outbound(name, RelationKind.ROUTES_TO):
        return _draft(
            "ROUTE_REFERENCE_CHANGED",
            Severity.MEDIUM,
            f"{name} addresses a route that changed",
            f"{name} names a route path, and the path or its matched handler "
            "differs in the target state.",
            Derivation.HIGH_CONFIDENCE_HEURISTIC,
            change,
            limitations=("Framework routing is not runtime-resolved.",),
        )

    if (
        change.symbol_kind in _VALUE_KINDS
        and target.has_outbound_route_reference(name)
    ):
        return _draft(
            "CONFIG_REFERENCE_CHANGED",
            Severity.MEDIUM,
            f"{name} holds a path that changed",
            f"{name} holds a route path matched to a handler by name. The value "
            "differs in the target state.",
            Derivation.HIGH_CONFIDENCE_HEURISTIC,
            change,
            limitations=("A matching name is not proof the route exists.",),
        )
    return None


def _export(
    change: SymbolChange, base: _Graphs, target: _Graphs
) -> FindingDraft | None:
    name = change.qualified_name
    was = base.has_inbound(name, RelationKind.EXPORTS)
    now = target.has_inbound(name, RelationKind.EXPORTS)
    if was and not now:
        return _draft(
            "EXPORT_REMOVED",
            Severity.HIGH,
            f"{name} is no longer exported",
            f"{name} was exported in the base state and is not in the target "
            "state. Importers outside this module can no longer reach it.",
            Derivation.DETERMINISTIC,
            change,
        )
    if now and not was:
        return _draft(
            "EXPORT_ADDED",
            Severity.INFO,
            f"{name} is newly exported",
            f"{name} is exported in the target state and was not in the base "
            "state.",
            Derivation.DETERMINISTIC,
            change,
        )
    return None


def _signature(change: SymbolChange) -> FindingDraft | None:
    if change.signature_change_class is SignatureChangeClass.NONE:
        return None
    name = change.qualified_name

    if (
        change.signature_change_class
        is SignatureChangeClass.ONLY_OPTIONAL_PARAMETERS_ADDED
        and change.body_change_class is BodyChangeClass.NONE
    ):
        return _draft(
            "PARAMETER_ADDED",
            Severity.MEDIUM,
            f"{name} gained an optional parameter",
            f"{name} takes one or more additional optional parameters. Existing "
            "call sites remain syntactically valid.",
            Derivation.DETERMINISTIC,
            change,
        )

    return _draft(
        "PUBLIC_SIGNATURE_CHANGED",
        Severity.HIGH,
        f"The signature of {name} changed",
        f"{name} declares a different signature in the target state. Call sites "
        "may no longer match it.",
        Derivation.DETERMINISTIC,
        change,
    )


def _body(change: SymbolChange, target: _Graphs) -> FindingDraft | None:
    """What changed inside the symbol, when nothing about it changed outside.

    Every rule here is `high_confidence_heuristic`. The classification is a
    syntax-level reading of which statements differ; it says nothing about what
    the code now does at runtime, and labeling it deterministic would let a
    reader take it for more than it is.
    """
    name = change.qualified_name
    body = change.body_change_class
    if body is BodyChangeClass.NONE:
        return None

    if target.has_inbound(name, RelationKind.ROUTES_TO):
        return _draft(
            "PUBLIC_CONTRACT_CHANGED",
            Severity.HIGH,
            f"The behavior of {name} changed and it answers a route",
            f"The body of {name} changed, and a route literal elsewhere resolves "
            "to it, so a caller outside this repository's control may depend on "
            "what it returns.",
            Derivation.HIGH_CONFIDENCE_HEURISTIC,
            change,
            limitations=("Framework routing is not runtime-resolved.",),
        )

    codes: dict[BodyChangeClass, tuple[str, str, str]] = {
        BodyChangeClass.RETURN_VALUE_CHANGED: (
            "RETURN_VALUE_CHANGED",
            f"What {name} returns changed",
            "A return statement in the body differs between the two states.",
        ),
        BodyChangeClass.ERROR_BEHAVIOR_CHANGED: (
            "ERROR_BEHAVIOR_CHANGED",
            f"How {name} raises changed",
            "A raise or throw statement that existed in the base state differs "
            "in the target state.",
        ),
        BodyChangeClass.STATE_INITIALIZATION_CHANGED: (
            "STATE_INITIALIZATION_CHANGED",
            f"What {name} initializes changed",
            "A constructor body changed, so instances may carry different "
            "state from the moment they are created.",
        ),
        BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED: (
            "PUBLIC_BEHAVIOR_CHANGED",
            f"The behavior of {name} changed",
            "Statements in the body differ between the two states.",
        ),
        BodyChangeClass.PUBLIC_CONTRACT_CHANGED: (
            "PUBLIC_CONTRACT_CHANGED",
            f"The contract of {name} changed",
            "The body changed in a way that reaches this symbol's callers.",
        ),
    }
    code, title, description = codes[body]
    severity = (
        Severity.HIGH
        if body is BodyChangeClass.PUBLIC_CONTRACT_CHANGED
        else Severity.MEDIUM
    )
    return _draft(
        code,
        severity,
        title,
        description,
        Derivation.HIGH_CONFIDENCE_HEURISTIC,
        change,
        limitations=(
            "Statement classification is syntactic and does not model runtime "
            "behavior.",
        ),
    )


def _independent(
    change: SymbolChange, *, target_graph: _Graphs
) -> list[FindingDraft]:
    """Rules that describe something the primary finding cannot.

    Only one applies so far, and it is narrower than it first appears. A
    documented *configuration key* earns a review prompt because the document
    usually quotes the value; a documented *function* does not, because its own
    finding already tells the reader the contract moved. The corpus draws that
    line (c012 against c015) and finding precision is a gate, so the rule stays
    where the corpus puts it.
    """
    if change.symbol_kind is not SymbolKind.CONFIG_KEY:
        return []
    if not target_graph.has_inbound(change.qualified_name, RelationKind.DOCUMENTS):
        return []
    return [
        _draft(
            "DOCUMENT_REVIEW_REQUIRED",
            Severity.LOW,
            f"A document describes {change.qualified_name}",
            "A document section names every segment of this key, so it may "
            "describe the value that changed.",
            Derivation.LOW_CONFIDENCE_HEURISTIC,
            change,
            limitations=(
                "The link is a word match and does not prove the document "
                "states this value.",
            ),
        )
    ]


def _architecture(
    violations: Sequence[ArchitectureViolation],
) -> list[FindingDraft]:
    return [
        FindingDraft(
            code="ARCHITECTURE_RULE_VIOLATED",
            severity=violation.severity,
            title=f"{violation.rule_id}: {violation.source} must not reach "
            f"{violation.target}",
            description=violation.description,
            derivation=Derivation.STATIC_RESOLVED,
            confidence=0.95,
            subject=violation.source,
            rule_id=violation.rule_id,
            remediation="Route the dependency through an allowed boundary.",
        )
        for violation in violations
    ]


def _renamed_file(change: FileChange) -> FindingDraft:
    return FindingDraft(
        code="FILE_RENAMED",
        severity=Severity.INFO,
        title=f"{change.base_path} was renamed to {change.path}",
        description="The two paths hold byte-identical content, so the rename "
        "is deterministic rather than a similarity score.",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
        subject=change.path,
    )


def _draft(
    code: str,
    severity: Severity,
    title: str,
    description: str,
    derivation: Derivation,
    change: SymbolChange,
    *,
    side: AnalysisSide = AnalysisSide.TARGET,
    remediation: str | None = None,
    limitations: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> FindingDraft:
    confidence = {
        Derivation.DETERMINISTIC: 1.0,
        Derivation.STATIC_RESOLVED: 0.95,
        Derivation.HIGH_CONFIDENCE_HEURISTIC: 0.7,
        Derivation.LOW_CONFIDENCE_HEURISTIC: 0.4,
    }[derivation]
    return FindingDraft(
        code=code,
        severity=severity,
        title=title,
        description=description,
        derivation=derivation,
        confidence=confidence,
        subject=change.qualified_name,
        subject_file=change.file_path,
        side=side,
        remediation=remediation,
        limitations=limitations,
        warnings=warnings,
    )


def _is_injection(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", text).lower()
    return any(marker in lowered for marker in _INJECTION_MARKERS)


def _is_package_script(change: SymbolChange) -> bool:
    if change.file_path.rsplit("/", 1)[-1] != "package.json":
        return False
    name = change.qualified_name
    return name == "scripts" or name.startswith("scripts.")


def severity_rank(severity: Severity) -> int:
    """Order severities most serious first."""
    return _SEVERITY_RANK[severity]
