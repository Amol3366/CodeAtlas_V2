"""The change analysis engine: two states in, one evidence-backed report out.

The engine never invokes Git and never resolves a ref. It is handed two
:class:`StateView`s and compares them. Git is one front-end that produces such
views; a plain directory is another, which is what lets the evaluation corpus
exercise exactly the code the product flows use rather than a parallel
implementation of it.

The pipeline is deliberately linear and each stage is timed, because "which
stage is slow" is a question the performance gate has to answer:

    file diff -> parse+resolve both sides -> symbol diff -> body classification
    -> impact -> architecture rules -> findings -> risk

Nothing here decides freshness, persistence, or which refs to compare. Those are
the application service's concerns; keeping them out is what makes this callable
from a test with two temporary directories.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from codeatlas.analysis.architecture import ArchitectureRule, evaluate_rules
from codeatlas.analysis.file_diff import compute_file_changes
from codeatlas.analysis.findings import FindingDraft, evaluate_findings
from codeatlas.analysis.impact import (
    GraphSide,
    ImpactBounds,
    ImpactResult,
    analyze_impact,
)
from codeatlas.analysis.risk import order_findings, overall_risk
from codeatlas.analysis.statement_diff import classify_body
from codeatlas.analysis.states import StateView
from codeatlas.analysis.symbol_diff import SymbolDiffInput, compute_symbol_changes
from codeatlas.contracts import (
    ChangeKind,
    FileChangeKind,
    OverallRisk,
    RelationKind,
    SymbolKind,
)
from codeatlas.domain.change import FileChange, SymbolChange
from codeatlas.domain.ids import file_id as build_file_id
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.extraction.resolution import SnapshotResolver
from codeatlas.parsing.registry import (
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
    ParserRegistry,
    default_registry,
)

_ANALYSIS_REPOSITORY_ID: Final[str] = "analysis"


@dataclass(frozen=True)
class AnalyzedState:
    """One parsed, resolved side of a change."""

    graph: GraphSide
    documents: Mapping[str, str]
    diagnostics: tuple[ParseDiagnostic, ...] = ()
    unparsed: tuple[str, ...] = ()


ParseKey = tuple[str, str, bytes]
"""Key for one parse: what the parse actually depends on.

`(relative_path, language, content digest)` -- and nothing else, because
nothing else varies. Every remaining field of the `ParseRequest` the engine
builds is derived from these: `repository_id` and `snapshot_id` are the same
constant on both sides, and `file_id` comes from the path.
"""


@dataclass(frozen=True)
class ChangeReport:
    """What the engine concluded, before any adapter renders it."""

    changed_files: tuple[FileChange, ...] = ()
    changed_symbols: tuple[SymbolChange, ...] = ()
    findings: tuple[FindingDraft, ...] = ()
    impact: ImpactResult = field(default_factory=ImpactResult)
    overall_risk: OverallRisk = OverallRisk.NONE
    base: AnalyzedState | None = None
    target: AnalyzedState | None = None
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    timing_ms: Mapping[str, float] = field(default_factory=dict)


class ChangeAnalysisEngine:
    """Compares two states and produces a risk-ordered, evidence-ready report."""

    def __init__(
        self,
        registry: ParserRegistry | None = None,
        bounds: ImpactBounds | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._resolver = SnapshotResolver()
        self._bounds = bounds or ImpactBounds()

    def analyze(
        self,
        base: StateView,
        target: StateView,
        *,
        rules: Sequence[ArchitectureRule] = (),
    ) -> ChangeReport:
        timings: dict[str, float] = {}
        warnings: list[str] = []
        limitations: list[str] = []

        with _timed(timings, "file_diff"):
            files = compute_file_changes(base, target)

        # One cache for both sides. The two states share every file the change
        # did not touch, and an unchanged file builds a byte-identical parse
        # request on each side -- so without this, ~all of the work is done
        # twice and one of two identical answers is discarded. Measured at 316 s
        # per side on this repository (ADR-0061).
        #
        # Scoped to this call deliberately: same process, same parser instance,
        # same bytes, so reuse is correct by construction and there is no
        # invalidation question to get wrong. A cache that outlived the call
        # would have one.
        #
        # **`parse_target` is no longer comparable to `parse_base`.** Whichever
        # side runs first pays for the shared files, so the split now reports
        # order rather than effort. Their sum is the number that means
        # something.
        parses: dict[ParseKey, ParseResult] = {}
        with _timed(timings, "parse_base"):
            base_state = self._analyze_state(base, parses)
        with _timed(timings, "parse_target"):
            target_state = self._analyze_state(target, parses)

        for state, side in ((base_state, "base"), (target_state, "target")):
            if state.unparsed:
                # A file the parser could not read is a hole in the analysis,
                # and a hole that is not reported reads exactly like a clean
                # result. Naming it is the whole point.
                warnings.append(f"PARSE_FAILED_{side.upper()}")
                limitations.append(
                    f"{len(state.unparsed)} file(s) in the {side} state could "
                    "not be parsed; symbols in them were not compared."
                )

        # A file over the size limit is excluded from the comparison rather
        # than refused (ADR-0045). Skipping it silently would trade a loud
        # failure for a quiet one, which for a change-assurance tool is the
        # worse defect -- so the omission is named here. Reported once across
        # both sides, because the same oversized file is normally in both and
        # two identical limitations read as two problems.
        oversized = sorted(
            {
                item.relative_path
                for view in (base, target)
                for item in view.excluded_files()
                if item.reason_code == "TOO_LARGE"
            }
        )
        if oversized:
            warnings.append("FILE_TOO_LARGE")
            limitations.append(
                f"{len(oversized)} file(s) exceed the maximum file size and "
                "were excluded from the comparison; changes inside them were "
                f"not detected: {', '.join(oversized)}."
            )

        with _timed(timings, "symbol_diff"):
            changes = compute_symbol_changes(
                _diff_input(base_state), _diff_input(target_state)
            )
            files = _promote_renames(files, changes)
            changes = self._classify_bodies(changes, base, target, target_state)

        with _timed(timings, "impact"):
            impact = analyze_impact(
                changes,
                base=base_state.graph,
                target=target_state.graph,
                bounds=self._bounds,
            )

        with _timed(timings, "architecture"):
            violations = evaluate_rules(
                rules, base=base_state.graph, target=target_state.graph
            )

        with _timed(timings, "findings"):
            drafts = evaluate_findings(
                changes,
                files=files,
                base=base_state.graph,
                target=target_state.graph,
                document_text=target_state.documents,
                violations=violations,
            )
            ordered = order_findings(drafts)

        for draft in ordered:
            warnings.extend(item for item in draft.warnings if item not in warnings)
            limitations.extend(
                item for item in draft.limitations if item not in limitations
            )
        warnings.extend(
            item for item in impact.warnings if item not in warnings
        )
        limitations.extend(
            item for item in impact.limitations if item not in limitations
        )

        return ChangeReport(
            changed_files=files,
            changed_symbols=changes,
            findings=ordered,
            impact=impact,
            overall_risk=overall_risk(ordered),
            base=base_state,
            target=target_state,
            warnings=tuple(warnings),
            limitations=tuple(limitations),
            timing_ms=timings,
        )

    def _analyze_state(
        self, state: StateView, parses: dict[ParseKey, ParseResult] | None = None
    ) -> AnalyzedState:
        """Parse every file of one state and resolve its references.

        Resolution runs over the whole state rather than the changed files
        alone. An edge is only meaningful against a complete symbol table, and
        resolving a subset would report a caller as unresolved merely because
        its target's file was not in the changed set.
        """
        files: list[FileRecord] = []
        symbols: list[SymbolRecord] = []
        references: list[SymbolReference] = []
        diagnostics: list[ParseDiagnostic] = []
        unparsed: list[str] = []
        documents: dict[str, str] = {}
        paths: dict[str, str] = {}

        for entry in state.list_files():
            identifier = build_file_id(_ANALYSIS_REPOSITORY_ID, entry.relative_path)
            paths[identifier] = entry.relative_path
            files.append(
                FileRecord(
                    file_id=identifier,
                    relative_path=entry.relative_path,
                    display_path=entry.relative_path,
                    content_hash=entry.content_hash,
                    language=entry.language,
                    classification=entry.classification,
                    size_bytes=entry.size_bytes,
                    line_count=entry.line_count,
                )
            )

            parser = self._registry.parser_for(entry.language)
            if parser is None:
                continue
            content = state.read_file(entry.relative_path)
            if content is None:
                unparsed.append(entry.relative_path)
                continue

            # The digest, not the state's declared `content_hash`: this must key
            # on the bytes actually handed to the parser. ADR-0043 normalises
            # line endings on the way here, and a key taken from the state's own
            # accounting could drift from what was parsed.
            cache_key: ParseKey = (
                entry.relative_path,
                entry.language,
                hashlib.blake2b(content, digest_size=16).digest(),
            )
            result = None if parses is None else parses.get(cache_key)
            if result is None:
                result = parser.parse(
                    ParseRequest(
                        repository_id=_ANALYSIS_REPOSITORY_ID,
                        snapshot_id=_ANALYSIS_REPOSITORY_ID,
                        file_id=identifier,
                        relative_path=entry.relative_path,
                        language=entry.language,
                        content=content,
                    )
                )
                if parses is not None:
                    parses[cache_key] = result
            diagnostics.extend(result.diagnostics)
            symbols.extend(result.symbols)
            references.extend(result.references)
            if not result.success:
                unparsed.append(entry.relative_path)
            if entry.language == "markdown":
                documents.update(_document_text(result.symbols, content))

        relations, _ = self._resolver.resolve(files, symbols, references)
        return AnalyzedState(
            graph=GraphSide(
                symbols={symbol.symbol_id: symbol for symbol in symbols},
                relations=relations,
                file_paths=paths,
                test_file_ids=frozenset(
                    record.file_id
                    for record in files
                    if record.classification is FileClassification.TEST_CODE
                ),
            ),
            documents=documents,
            diagnostics=tuple(diagnostics),
            unparsed=tuple(sorted(set(unparsed))),
        )

    def _classify_bodies(
        self,
        changes: Sequence[SymbolChange],
        base: StateView,
        target: StateView,
        target_state: AnalyzedState,
    ) -> tuple[SymbolChange, ...]:
        """Attach a statement-level classification to each modified body.

        Route adjacency is decided here rather than in the differ, because it
        needs the resolved target graph: a symbol is route-adjacent when a route
        literal somewhere else resolves *to* it, which no single file states.
        """
        routed: set[str] = set()
        for relation in target_state.graph.relations:
            if relation.kind is not RelationKind.ROUTES_TO:
                continue
            target_id = relation.target_symbol_id
            if target_id is None:
                continue
            symbol = target_state.graph.symbols.get(target_id)
            if symbol is not None:
                routed.add(symbol.qualified_name)

        classified: list[SymbolChange] = []
        for change in changes:
            if (
                change.change_kind not in {ChangeKind.MODIFIED, ChangeKind.MOVED}
                or _is_data(change)
            ):
                classified.append(change)
                continue
            base_content = base.read_file(change.base_file_path or change.file_path)
            target_content = target.read_file(change.file_path)
            if base_content is None or target_content is None:
                classified.append(change)
                continue
            if (
                change.base_start_line is None
                or change.base_end_line is None
                or change.target_start_line is None
                or change.target_end_line is None
            ):
                classified.append(change)
                continue

            base_range = (change.base_start_line, change.base_end_line)
            target_range = (change.target_start_line, change.target_end_line)
            if change.change_kind is ChangeKind.MOVED:
                # A moved symbol's definition line differs whenever its
                # signature does; classifying it would call every signature
                # change a body change. Compare the bodies alone, so F5's
                # "body unchanged" condition is a real condition (c020 vs
                # c022).
                base_range = (base_range[0] + 1, base_range[1])
                target_range = (target_range[0] + 1, target_range[1])
                if base_range[0] > base_range[1] or target_range[0] > target_range[1]:
                    classified.append(change)
                    continue

            body = classify_body(
                base_content,
                target_content,
                _language_of(change.file_path),
                base_range,
                target_range,
                is_route_adjacent=change.qualified_name in routed,
            )
            classified.append(
                SymbolChange(
                    qualified_name=change.qualified_name,
                    symbol_kind=change.symbol_kind,
                    change_kind=change.change_kind,
                    file_path=change.file_path,
                    base_file_path=change.base_file_path,
                    base_start_line=change.base_start_line,
                    base_end_line=change.base_end_line,
                    target_start_line=change.target_start_line,
                    target_end_line=change.target_end_line,
                    signature_change_class=change.signature_change_class,
                    public=change.public,
                    body_change_class=body.body_class,
                    evidence_start_line=(
                        body.evidence_span[0] if body.evidence_span else None
                    ),
                    evidence_end_line=(
                        body.evidence_span[1] if body.evidence_span else None
                    ),
                )
            )
        return tuple(classified)


def _promote_renames(
    files: tuple[FileChange, ...],
    changes: Sequence[SymbolChange],
) -> tuple[FileChange, ...]:
    """Pair a deleted and an added file that share a moved symbol (decision 3).

    Content-hash equality already produced `renamed` entries in the file diff;
    this is the fallback for a rename *with* edits, where the hash cannot
    speak but a uniquely moved symbol identity can. The pairing must be
    unambiguous in both directions — a guess is never emitted. The moved
    symbols themselves stay `moved`; the finding rules already report a move
    inside a renamed file through the rename plus the symbol's own signature
    and body rules, never as a second move fact.
    """
    deleted = {item.path for item in files if item.kind is FileChangeKind.DELETED}
    added = {item.path for item in files if item.kind is FileChangeKind.ADDED}

    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for change in changes:
        if change.change_kind is not ChangeKind.MOVED:
            continue
        source = change.base_file_path
        if source in deleted and change.file_path in added:
            forward.setdefault(source, set()).add(change.file_path)
            backward.setdefault(change.file_path, set()).add(source)

    pairs = {
        (source, next(iter(targets)))
        for source, targets in forward.items()
        if len(targets) == 1 and len(backward[next(iter(targets))]) == 1
    }
    if not pairs:
        return files

    paired_sources = {source for source, _ in pairs}
    paired_targets = {target for _, target in pairs}
    promoted = [
        item
        for item in files
        if not (
            (item.kind is FileChangeKind.DELETED and item.path in paired_sources)
            or (item.kind is FileChangeKind.ADDED and item.path in paired_targets)
        )
    ]
    promoted.extend(
        FileChange(
            path=target,
            kind=FileChangeKind.RENAMED,
            base_path=source,
            content_hash_changed=True,
        )
        for source, target in sorted(pairs)
    )
    return tuple(sorted(promoted, key=lambda item: item.path))


def _diff_input(state: AnalyzedState) -> SymbolDiffInput:
    return SymbolDiffInput(
        symbols=list(state.graph.symbols.values()),
        relations=list(state.graph.relations),
        file_paths=dict(state.graph.file_paths),
    )


def _is_data(change: SymbolChange) -> bool:
    """Whether this symbol has no code body to classify."""
    return change.symbol_kind in {
        SymbolKind.DOCUMENT_SECTION,
        SymbolKind.CONFIG_KEY,
        SymbolKind.MODULE,
    }


def _document_text(
    symbols: Sequence[SymbolRecord], content: bytes
) -> dict[str, str]:
    """The text of each document section, for the untrusted-content rule."""
    lines = content.decode("utf-8-sig", errors="replace").splitlines()
    return {
        symbol.qualified_name: "\n".join(
            lines[symbol.start_line - 1 : symbol.end_line]
        )
        for symbol in symbols
        if symbol.kind is SymbolKind.DOCUMENT_SECTION
    }


def _language_of(relative_path: str) -> str:
    suffix = relative_path.rsplit(".", 1)[-1].lower()
    return {
        "py": "python",
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "mjs": "javascript",
        "cjs": "javascript",
    }.get(suffix, suffix)


class _timed:
    """Record one stage's wall time into the report's timing map."""

    def __init__(self, into: dict[str, float], name: str) -> None:
        self._into = into
        self._name = name
        self._started = 0.0

    def __enter__(self) -> None:
        self._started = time.perf_counter()

    def __exit__(self, *_: object) -> None:
        self._into[self._name] = (time.perf_counter() - self._started) * 1000


__all__ = [
    "AnalyzedState",
    "ChangeAnalysisEngine",
    "ChangeReport",
]
