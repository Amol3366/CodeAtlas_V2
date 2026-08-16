"""Change analysis as a use case: freshness, states, engine, persistence.

The engine compares two states and knows nothing else. This service supplies
everything it deliberately does not: which refs to compare, whether the active
snapshot is current enough to serve as one of the states, how to turn a finding
into hash-verified evidence, and where the result is stored.

The freshness gate is the part worth reading twice. A working-tree preflight
against a stale index would answer a question about a repository that no longer
exists, so the tree is scanned first and re-indexed when it has drifted. If that
index fails, the analysis fails with it and the previous active snapshot is left
exactly as it was — a stale-but-valid snapshot is strictly better than a
half-built one.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from codeatlas.analysis.architecture import load_rules
from codeatlas.analysis.engine import ChangeAnalysisEngine, ChangeReport
from codeatlas.analysis.states import (
    DirectoryStateView,
    GitBlobStateView,
    StateView,
)
from codeatlas.application.indexing import IndexRepositoryService
from codeatlas.contracts import (
    AnalysisSide,
    AnalysisStateRef,
    ChangeAnalysisKind,
    ChangeAnalysisReport,
    ChangeAnalysisStatus,
    ChangedFile,
    ChangedSymbol,
    ChangeEvidenceItem,
    ChangeKind,
    Derivation,
    Finding,
    SnapshotFreshness,
    locate_finding,
)
from codeatlas.contracts import ImpactEdge as ContractImpactEdge
from codeatlas.domain.change import SymbolChange
from codeatlas.domain.errors import (
    ChangeAnalysisNotFoundError,
    ChangeAnalysisRequiresGitError,
    RepositoryNotFoundError,
)
from codeatlas.extraction.resolution import RESOLVER_VERSION
from codeatlas.repositories.git_diff import GitDiffAdapter
from codeatlas.repositories.git_state import GitAdapter
from codeatlas.storage.sqlite.connection import write_transaction
from codeatlas.storage.sqlite.stores import (
    ChangeAnalysisStore,
    RepositoryStore,
    SnapshotStore,
)

_WORKING_TREE_REF = "working-tree"


@dataclass(frozen=True)
class ChangeAnalysisRequest:
    """One request to compare two states of a repository."""

    repository_id: str
    base_ref: str = "HEAD"
    target_ref: str | None = None
    request_id: str = ""


class ChangeAnalysisService:
    """Runs and persists change analyses for a registered repository."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        analyses: ChangeAnalysisStore,
        indexing: IndexRepositoryService,
        git: GitAdapter,
        diff: GitDiffAdapter,
        connection: Connection,
        engine: ChangeAnalysisEngine | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._analyses = analyses
        self._indexing = indexing
        self._git = git
        self._diff = diff
        self._connection = connection
        self._engine = engine or ChangeAnalysisEngine()

    def analyze_working_tree(
        self, request: ChangeAnalysisRequest
    ) -> ChangeAnalysisReport:
        """Compare the working tree against a base ref, refreshing the index first."""
        root = self._resolve(request.repository_id)
        state = self._git.read_state(root)
        if not state.is_repository:
            raise ChangeAnalysisRequiresGitError(
                "A working-tree analysis needs a base, and only a Git "
                "repository can supply one."
            )

        base_commit = self._diff.resolve_ref(root, request.base_ref)
        # Freshness first. Analyzing a drifted tree against a stale index would
        # answer a question about a repository that no longer exists.
        snapshot_id = self._refresh(request.repository_id)

        base_view = GitBlobStateView(root, base_commit, self._diff)
        target_view = DirectoryStateView(root)
        report = self._engine.analyze(
            base_view, target_view, rules=load_rules(root)
        )
        return self._persist(
            request=request,
            repository_id=request.repository_id,
            kind=ChangeAnalysisKind.WORKING_TREE,
            report=report,
            base=AnalysisStateRef(
                ref=request.base_ref,
                commit=base_commit,
                snapshot_id=None,
                freshness=SnapshotFreshness.STALE,
            ),
            target=AnalysisStateRef(
                ref=_WORKING_TREE_REF,
                commit=state.head_commit,
                snapshot_id=snapshot_id,
                freshness=SnapshotFreshness.FRESH,
            ),
            base_view=base_view,
            target_view=target_view,
        )

    def analyze_since(
        self, request: ChangeAnalysisRequest, since_ref: str
    ) -> ChangeAnalysisReport:
        """Analyze from where ``since_ref`` and HEAD diverged, through to HEAD.

        Not the same as a base of ``since_ref``: a two-dot diff against a trunk
        that has moved reports the trunk's own new commits as changes to this
        branch, inverted. Only the merge base answers "what did I change".

        Lives here rather than in the CLI because resolving a repository root
        and invoking Git is repository logic, and an adapter that did it would
        both cross the boundary and leave the other adapters unable to offer
        the same capability.
        """
        root = self._resolve(request.repository_id)
        state = self._git.read_state(root)
        if not state.is_repository:
            raise ChangeAnalysisRequiresGitError(
                "A --since analysis needs a Git repository to find the merge "
                "base in."
            )

        base_commit = self._diff.merge_base(root, since_ref)
        return self.analyze_commit_range(
            ChangeAnalysisRequest(
                repository_id=request.repository_id,
                base_ref=base_commit,
                target_ref="HEAD",
                request_id=request.request_id,
            )
        )

    def analyze_commit_range(
        self, request: ChangeAnalysisRequest
    ) -> ChangeAnalysisReport:
        """Compare two commits, reading both sides from Git objects."""
        root = self._resolve(request.repository_id)
        state = self._git.read_state(root)
        if not state.is_repository:
            raise ChangeAnalysisRequiresGitError(
                "A commit-range analysis requires a Git repository."
            )

        base_commit = self._diff.resolve_ref(root, request.base_ref)
        target_commit = self._diff.resolve_ref(root, request.target_ref or "HEAD")

        base_view = GitBlobStateView(root, base_commit, self._diff)
        target_view = GitBlobStateView(root, target_commit, self._diff)
        report = self._engine.analyze(
            base_view, target_view, rules=load_rules(root)
        )
        return self._persist(
            request=request,
            repository_id=request.repository_id,
            kind=ChangeAnalysisKind.COMMIT_RANGE,
            report=report,
            base=AnalysisStateRef(
                ref=request.base_ref,
                commit=base_commit,
                snapshot_id=None,
                freshness=SnapshotFreshness.STALE,
            ),
            target=AnalysisStateRef(
                ref=request.target_ref or "HEAD",
                commit=target_commit,
                snapshot_id=None,
                # A commit range answers a question about two historical
                # states. Neither is the working tree, so neither is
                # `FRESH`. `STALE` is the honest label in the existing
                # enum: deliberately not current. Adding a `HISTORICAL`
                # value would change a published contract enum for a
                # distinction `AnalysisSide` already carries.
                freshness=SnapshotFreshness.STALE,
            ),
            base_view=base_view,
            target_view=target_view,
        )

    def get(self, analysis_id: str) -> ChangeAnalysisReport:
        """Read a persisted analysis, or say plainly that it is not there."""
        report = self._analyses.get(analysis_id)
        if report is None:
            raise ChangeAnalysisNotFoundError("No analysis with that ID exists.")
        return report

    def list_for_repository(self, repository_id: str) -> tuple[str, ...]:
        self._resolve(repository_id)
        return self._analyses.list_for_repository(repository_id)

    def _resolve(self, repository_id: str) -> Path:
        repository = self._repositories.get(repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")
        return Path(repository.canonical_root)

    def _refresh(self, repository_id: str) -> str | None:
        """Bring the active snapshot up to date with the tree, or build one.

        Indexing is idempotent and skips an unchanged tree, so this is the
        measured incremental path rather than a rebuild. A failure propagates:
        the previous active snapshot stays active and untouched, and the
        analysis does not pretend to have examined a state it never saw.
        """
        result = self._indexing.index(repository_id)
        return result.snapshot.snapshot_id

    def _persist(
        self,
        *,
        request: ChangeAnalysisRequest,
        repository_id: str,
        kind: ChangeAnalysisKind,
        report: ChangeReport,
        base: AnalysisStateRef,
        target: AnalysisStateRef,
        base_view: StateView,
        target_view: StateView,
    ) -> ChangeAnalysisReport:
        analysis_id = f"analysis_{uuid.uuid4().hex}"
        created = datetime.now(UTC)

        evidence, findings = _build_evidence(
            analysis_id=analysis_id,
            report=report,
            base_view=base_view,
            target_view=target_view,
        )

        limitations = list(report.limitations)
        # A resolver bump does not reindex. Until this repository is
        # reindexed, test-gap data came from the older derivation passes and
        # will overstate gaps. Reporting it without saying so is exactly the
        # failure this product exists to prevent. An absent or unloadable
        # snapshot is a different condition (already reported elsewhere), so
        # it is deliberately not treated as stale here.
        snapshot = (
            self._snapshots.get(target.snapshot_id)
            if target.snapshot_id is not None
            else None
        )
        if snapshot is not None and snapshot.resolver_version != RESOLVER_VERSION:
            limitations.append(
                "Test-gap data was produced by an older resolver "
                f"({snapshot.resolver_version}; current is {RESOLVER_VERSION}) "
                "and may overstate gaps. Reindex this repository to refresh it."
            )

        contract = ChangeAnalysisReport(
            analysis_id=analysis_id,
            request_id=request.request_id or analysis_id,
            repository_id=repository_id,
            kind=kind,
            status=ChangeAnalysisStatus.COMPLETED,
            overall_risk=report.overall_risk,
            base=base,
            target=target,
            changed_files=[
                ChangedFile(
                    path=item.path,
                    change_kind=item.kind,
                    base_path=item.base_path,
                    content_hash_changed=item.content_hash_changed,
                )
                for item in report.changed_files
            ],
            changed_symbols=[
                _contract_symbol(item) for item in report.changed_symbols
            ],
            impact_edges=[
                ContractImpactEdge(
                    source=edge.source,
                    target=edge.target,
                    kind=edge.kind,
                    derivation=edge.derivation,
                    confidence=edge.confidence,
                )
                for edge in report.impact.edges
            ],
            findings=findings,
            evidence=evidence,
            test_gaps=list(report.impact.test_gaps),
            test_gap_reasons=list(report.impact.test_gap_reasons),
            warnings=list(report.warnings),
            limitations=limitations,
            timing_ms=dict(report.timing_ms),
            created_at=created,
            completed_at=datetime.now(UTC),
        )

        with write_transaction(self._connection):
            self._analyses.save(contract)
        return contract


def _contract_symbol(change: SymbolChange) -> ChangedSymbol:
    # A base line range with no base path is a citation with no file, which the
    # contract refuses. When a symbol did not move, its base path is its own
    # path, and naming it explicitly is what makes the base range citable.
    base_path = change.base_file_path
    if base_path is None and (
        change.base_start_line is not None or change.base_end_line is not None
    ):
        base_path = change.file_path
    return ChangedSymbol(
        qualified_name=change.qualified_name,
        symbol_kind=change.symbol_kind,
        change_kind=change.change_kind,
        file_path=change.file_path,
        base_file_path=base_path,
        base_start_line=change.base_start_line,
        base_end_line=change.base_end_line,
        target_start_line=change.target_start_line,
        target_end_line=change.target_end_line,
        signature_changed=change.signature_change_class.value != "none",
        public=change.public,
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _build_evidence(
    *,
    analysis_id: str,
    report: ChangeReport,
    base_view: StateView,
    target_view: StateView,
) -> tuple[list[ChangeEvidenceItem], list[Finding]]:
    """Turn each finding's subject into a hash-verified citation.

    Every citation is read from the side it belongs to and hashed at analysis
    time, base side included. A commit blob is immutable, so base evidence is
    historical by construction — it is labeled ``base`` and never presented as
    the current snapshot's content.

    A finding whose subject cannot be cited is **dropped**, not emitted with an
    empty citation. The contract requires at least one evidence ID, and a
    finding nobody can check is exactly the kind of claim this product exists to
    refuse.
    """
    # Keyed by name *and* file. A qualified name is not unique across a
    # repository, and keying on the name alone let two changed symbols called
    # `total`, in different modules, collapse to whichever the dict saw last —
    # so both findings cited one file's lines and the other file's finding
    # pointed at code it was not about. That is a Section 4.1 violation, not a
    # rendering problem, and it is ADR-0042's rule ("pair within the file
    # first") reaching a surface that ruling did not touch.
    by_location = {
        (item.qualified_name, item.file_path): item
        for item in report.changed_symbols
    }
    by_name = {item.qualified_name: item for item in report.changed_symbols}
    evidence: dict[str, ChangeEvidenceItem] = {}
    findings: list[Finding] = []

    for draft in report.findings:
        # A symbol draft resolves *only* by location. Falling back to the name
        # would restore the ambiguity this key exists to remove, and silently:
        # the wrong citation still renders as a valid finding. A file-level or
        # architecture draft carries no file and keeps the name lookup, which
        # for those subjects — a path, a rule source — misses and falls through
        # to `_cite_file`, as it always did.
        change = (
            by_location.get((draft.subject, draft.subject_file))
            if draft.subject_file is not None
            else by_name.get(draft.subject)
        )
        item = _cite(
            analysis_id=analysis_id,
            draft_side=draft.side,
            change=change,
            subject=draft.subject,
            base_view=base_view,
            target_view=target_view,
        )
        if item is None:
            continue
        evidence.setdefault(item.evidence_id, item)
        # Derived through the same helper the stored path uses, so a fresh
        # report and a reloaded one cannot disagree (ADR-0054). `draft.subject`
        # is not read directly here for exactly that reason: the rehydration
        # path has no draft, and two derivations would be two things to keep in
        # step.
        subject, file_path = locate_finding(
            [item.evidence_id], {item.evidence_id: item}
        )
        findings.append(
            Finding(
                code=draft.code,
                severity=draft.severity,
                title=draft.title,
                description=draft.description,
                derivation=draft.derivation,
                confidence=draft.confidence,
                evidence_ids=[item.evidence_id],
                remediation=draft.remediation,
                limitations=list(draft.limitations),
                subject=subject,
                file_path=file_path,
            )
        )

    return sorted(evidence.values(), key=lambda item: item.evidence_id), findings


def _cite(
    *,
    analysis_id: str,
    draft_side: AnalysisSide,
    change: SymbolChange | None,
    subject: str,
    base_view: StateView,
    target_view: StateView,
) -> ChangeEvidenceItem | None:
    if change is None:
        # A file-level finding cites the file itself.
        return _cite_file(
            analysis_id=analysis_id, path=subject, view=target_view
        )

    deleted = change.change_kind is ChangeKind.DELETED
    side = AnalysisSide.BASE if deleted or draft_side is AnalysisSide.BASE else (
        AnalysisSide.TARGET
    )
    view = base_view if side is AnalysisSide.BASE else target_view
    path = (
        (change.base_file_path or change.file_path)
        if side is AnalysisSide.BASE
        else change.file_path
    )
    start, end = (
        (change.base_start_line, change.base_end_line)
        if side is AnalysisSide.BASE
        else (change.target_start_line, change.target_end_line)
    )
    if start is None or end is None:
        return None

    content = view.read_file(path)
    if content is None:
        return None
    excerpt = _excerpt(content, start, end)
    if excerpt is None:
        return None

    return ChangeEvidenceItem(
        evidence_id=_evidence_id(analysis_id, side, path, start, end),
        side=side,
        file_path=path,
        symbol=change.qualified_name,
        start_line=start,
        end_line=end,
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _cite_file(
    *, analysis_id: str, path: str, view: StateView
) -> ChangeEvidenceItem | None:
    content = view.read_file(path)
    if content is None:
        return None
    text = content.decode("utf-8", errors="replace")
    lines = max(len(text.splitlines()), 1)
    return ChangeEvidenceItem(
        evidence_id=_evidence_id(analysis_id, AnalysisSide.TARGET, path, 1, lines),
        side=AnalysisSide.TARGET,
        file_path=path,
        symbol=None,
        start_line=1,
        end_line=lines,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _excerpt(content: bytes, start: int, end: int) -> str | None:
    lines = content.decode("utf-8", errors="replace").splitlines()
    if start < 1 or end < start or end > len(lines):
        # A range the file cannot support is a broken citation. Refusing it is
        # the invariant: evidence is validated before it leaves the service.
        return None
    return "\n".join(lines[start - 1 : end])


def _evidence_id(
    analysis_id: str, side: AnalysisSide, path: str, start: int, end: int
) -> str:
    digest = hashlib.sha256(
        "\x1f".join((analysis_id, side.value, path, str(start), str(end))).encode()
    ).hexdigest()
    return f"ev_{digest[:32]}"


def unique_evidence_ids(items: Sequence[ChangeEvidenceItem]) -> set[str]:
    """Helper for adapters that need to check citation membership."""
    return {item.evidence_id for item in items}
