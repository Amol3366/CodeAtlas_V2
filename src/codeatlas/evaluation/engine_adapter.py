"""Runs the Phase 1 engine against the Phase 0 evaluation corpus.

Phase 1 implements one intent — `EXACT_SYMBOL` — for Python fixtures. Every case
outside that scope is emitted as an explicit abstention rather than a zero score,
because "not implemented" and "answered wrongly" are different facts and the
baseline must not blur them.

The dataset declares its own snapshot labels (for example `python-v1`) while the
engine derives snapshot IDs from content. Predictions therefore carry the case's
declared snapshot ID so they align with the gold corpus, but only after the
evidence has been validated against the engine's own active snapshot. Nothing is
emitted that the engine did not itself verify.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from codeatlas.analysis.engine import ChangeAnalysisEngine, ChangeReport
from codeatlas.analysis.states import DirectoryStateView
from codeatlas.application.container import build_services
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import (
    AnalysisSide,
    ChangeKind,
    FileChangeKind,
    SymbolKind,
)
from codeatlas.conversations.pipeline import AnswerPipeline, AnswerRequest
from codeatlas.domain.errors import CodeAtlasError
from codeatlas.evaluation.dataset import (
    ChangeCase,
    Dataset,
    QueryCase,
    StateSpec,
)
from codeatlas.evaluation.runner import (
    ChangePrediction,
    EvidencePrediction,
    FindingPrediction,
    PredictionFile,
    QueryPrediction,
)
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SUPPORTED_INTENT = "EXACT_SYMBOL"

# Phase 3 answers relation intents from stored relations. Each maps to one
# `GraphQueryService` method; nothing here re-derives a relation.
GRAPH_INTENTS: dict[str, str] = {
    "CALLERS": "callers",
    "DEPENDENCIES": "dependencies",
    "EXPORTS": "exports",
    "RELATED_TESTS": "related_tests",
    "TRACE_FLOW": "trace",
}
# Phase 2 adds lexical retrieval, so documents and configuration keys can now be
# answered. Everything still unimplemented abstains rather than guessing.
LEXICAL_INTENTS = ("CONFIG_LOOKUP", "DOCUMENT_LOOKUP")
SUPPORTED_INTENTS = (SUPPORTED_INTENT, *LEXICAL_INTENTS, *GRAPH_INTENTS)
SUPPORTED_FIXTURES = ("python_app", "docs_config", "mixed_app")


def predict_exact_symbols(
    dataset: Dataset,
    fixtures: Sequence[str] = SUPPORTED_FIXTURES,
    *,
    record_timings: bool = True,
) -> PredictionFile:
    """Answer every supported case with the real engine; abstain elsewhere.

    Set ``record_timings`` to ``False`` for a tracked baseline artifact. Wall
    times differ on every machine and every run, so including them would make a
    committed baseline impossible to verify byte-for-byte. Correctness metrics
    are unaffected; performance is measured separately and reported with its
    hardware, per `CLAUDE.md` Section 19.3.
    """
    supported = set(fixtures)
    predictions: list[QueryPrediction] = []

    with tempfile.TemporaryDirectory(prefix="codeatlas-eval-") as workspace:
        database_path = Path(workspace) / "evaluation.sqlite"
        with connect(database_path) as connection:
            apply_migrations(connection)
            services = build_services(connection)
            indexed: dict[str, str] = {}

            for case in dataset.query_cases:
                if (
                    case.intent not in SUPPORTED_INTENTS
                    or case.repository_fixture not in supported
                ):
                    predictions.append(_abstention(case))
                    continue

                repository_id = indexed.get(case.repository_fixture)
                if repository_id is None:
                    fixture_root = dataset.fixtures_root / _fixture_root(
                        dataset, case.repository_fixture
                    )
                    repository = services.registration.register(
                        RegisterRepositoryRequest(path=str(fixture_root))
                    )
                    services.indexing.index(repository.repository_id)
                    repository_id = repository.repository_id
                    indexed[case.repository_fixture] = repository_id

                predictions.append(
                    _answer(
                        services,
                        repository_id,
                        case,
                        record_timings=record_timings,
                    )
                )

    return PredictionFile(
        implementation_status="implemented",
        query_predictions=predictions,
        change_predictions=[],
    )


def _answer(
    services: object,
    repository_id: str,
    case: QueryCase,
    *,
    record_timings: bool = True,
) -> QueryPrediction:
    started = time.perf_counter()
    try:
        if case.intent == SUPPORTED_INTENT:
            response = services.lookup.lookup(  # type: ignore[attr-defined]
                SymbolLookupRequest(
                    repository_id=repository_id,
                    query=_query_term(case),
                    request_id=f"eval_{case.id}",
                )
            )
        elif case.intent in GRAPH_INTENTS:
            method = getattr(
                services.graph,  # type: ignore[attr-defined]
                GRAPH_INTENTS[case.intent],
            )
            response = method(
                GraphQueryRequest(
                    repository_id=repository_id,
                    symbol=_query_term(case),
                    request_id=f"eval_{case.id}",
                )
            )
        else:
            # Document and configuration questions are answered lexically. The
            # results are labeled `high_confidence_heuristic` by the service, so
            # the corpus is being told exactly how the answer was derived.
            response = services.search.search_text(  # type: ignore[attr-defined]
                SearchRequest(
                    repository_id=repository_id,
                    query=_query_term(case),
                    request_id=f"eval_{case.id}",
                )
            )
    except CodeAtlasError:
        return _abstention(case)

    duration_ms = (time.perf_counter() - started) * 1000 if record_timings else 0.0
    return QueryPrediction(
        case_id=case.id,
        ranked_symbols=[
            item.symbol for item in response.evidence if item.symbol is not None
        ],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id=item.evidence_id,
                # The engine validated this evidence against its own active
                # snapshot; the dataset's declared label is applied only for
                # comparison with the gold corpus.
                snapshot_id=case.snapshot_id,
                file_path=item.file_path,
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in response.evidence
        ],
        relation_paths=[
            " -> ".join(step.target for step in path.steps)
            for path in response.relation_paths
        ],
        claims=[claim.text for claim in response.answer.claims],
        abstained=not response.evidence,
        duration_ms=duration_ms,
    )


def _abstention(case: QueryCase) -> QueryPrediction:
    return QueryPrediction(
        case_id=case.id,
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=True,
        duration_ms=0.0,
    )


def _query_term(case: QueryCase) -> str:
    """Use the case's expected symbol as the exact lookup term.

    Phase 1 has no natural-language intent classifier. Feeding the declared
    symbol measures resolution accuracy, which is what this phase built; it does
    not measure question understanding, which it did not.
    """
    if case.expected_symbols:
        return case.expected_symbols[0]
    return case.question


def _fixture_root(dataset: Dataset, fixture_id: str) -> str:
    for fixture in dataset.fixtures:
        if fixture.id == fixture_id:
            return fixture.root
    raise KeyError(f"unknown fixture: {fixture_id}")


# --- Phase 7: conceptual prediction, with and without the semantic layer ------


def predict_conceptual(
    dataset: Dataset,
    *,
    semantic: bool,
    reranker: object | None = None,
    explainer: object | None = None,
    record_timings: bool = True,
) -> PredictionFile:
    """Answer every case through `AnswerPipeline`, optionally with fusion.

    **One switch, one difference.** Both runs use the same pipeline, the same
    services, the same corpus, and the verbatim question; ``semantic`` decides
    only whether a fusion layer is attached. Any other difference between the
    two runs would make the measured uplift an artifact of this function rather
    than a property of semantic retrieval, which is the one thing P7-06 exists
    to find out.

    The question is asked **verbatim**. `predict_exact_symbols` substitutes the
    declared symbol, which measures resolution rather than understanding;
    doing that here would hand the answer to both runs and guarantee they tie.
    """
    predictions: list[QueryPrediction] = []

    with tempfile.TemporaryDirectory(prefix="codeatlas-conceptual-") as workspace:
        database_path = Path(workspace) / "evaluation.sqlite"
        with connect(database_path) as connection:
            apply_migrations(connection)
            services = build_services(connection)
            indexed: dict[str, str] = {}
            pipelines: dict[str, AnswerPipeline] = {}

            for case in dataset.query_cases:
                repository_id = indexed.get(case.repository_fixture)
                if repository_id is None:
                    fixture_root = dataset.fixtures_root / _fixture_root(
                        dataset, case.repository_fixture
                    )
                    repository = services.registration.register(
                        RegisterRepositoryRequest(path=str(fixture_root))
                    )
                    services.indexing.index(repository.repository_id)
                    repository_id = repository.repository_id
                    indexed[case.repository_fixture] = repository_id
                    pipelines[case.repository_fixture] = _conceptual_pipeline(
                        connection,
                        services,
                        repository_id,
                        semantic=semantic,
                        reranker=reranker,
                        explainer=explainer,
                    )

                predictions.append(
                    _answer_conceptually(
                        pipelines[case.repository_fixture],
                        repository_id,
                        case,
                        record_timings=record_timings,
                    )
                )

    return PredictionFile(
        implementation_status="implemented",
        query_predictions=predictions,
        change_predictions=[],
    )


def _conceptual_pipeline(
    connection: object,
    services: object,
    repository_id: str,
    *,
    semantic: bool,
    reranker: object | None = None,
    explainer: object | None = None,
) -> AnswerPipeline:
    """Build the pipeline for one run, attaching fusion only when asked.

    Imports of the semantic package are deliberately local: the deterministic
    run must work on an installation where the optional extras were never
    installed, and a module-scope import would break that before the first
    case ran.

    ``explainer`` is threaded through for the same reason ``reranker`` is: an
    A/B must differ in exactly one thing, and the only honest way to measure
    what generation changes is to run the identical corpus, services, and
    questions with it attached and detached.
    """
    lookup = services.lookup  # type: ignore[attr-defined]
    graph = services.graph  # type: ignore[attr-defined]
    search = services.search  # type: ignore[attr-defined]
    if not semantic:
        return AnswerPipeline(
            lookup=lookup,
            graph=graph,
            search=search,
            explainer=explainer,  # type: ignore[arg-type]
        )

    from datetime import UTC, datetime

    from codeatlas.application.semantic_fusion import SemanticFusionService
    from codeatlas.application.semantic_status import SemanticStatusService
    from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
    from codeatlas.retrieval.semantic import SemanticSearchService
    from codeatlas.semantic.pipeline import SnapshotEmbedder
    from codeatlas.semantic.vector_store import InMemoryVectorStore
    from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore
    from codeatlas.storage.sqlite.stores import (
        EvidenceStore,
        FileStore,
        RepositoryStore,
        SnapshotStore,
    )

    ProviderPolicyStore(connection).set(  # type: ignore[arg-type]
        ProviderPolicy(
            repository_id=repository_id,
            embedding_provider=EmbeddingProviderKind.LOCAL,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=datetime.now(UTC),
        )
    )
    snapshots = SnapshotStore(connection)  # type: ignore[arg-type]
    active = snapshots.get_active(repository_id)
    if active is None:  # pragma: no cover - the index above just activated one
        raise EvaluationAdapterError("the fixture has no active snapshot")

    vectors = InMemoryVectorStore()
    outcome = SnapshotEmbedder(
        connection=connection,  # type: ignore[arg-type]
        vectors=vectors,
    ).embed_snapshot(repository_id, active.snapshot_id)
    if outcome.warning is not None or outcome.coverage != 1.0:
        # A partially embedded corpus would understate the layer, and reporting
        # that number as "semantic uplift" would be measuring an installation
        # problem. Refuse rather than publish it.
        raise EvaluationAdapterError(
            "the semantic run needs complete coverage; got "
            f"coverage={outcome.coverage} warning={outcome.warning}"
        )

    return AnswerPipeline(
        lookup=lookup,
        graph=graph,
        search=search,
        fusion=SemanticFusionService(
            repositories=RepositoryStore(connection),  # type: ignore[arg-type]
            snapshots=snapshots,
            files=FileStore(connection),  # type: ignore[arg-type]
            evidence=EvidenceStore(connection),  # type: ignore[arg-type]
            status=SemanticStatusService(connection),  # type: ignore[arg-type]
            semantic=SemanticSearchService(
                connection=connection,  # type: ignore[arg-type]
                vectors=vectors,
            ),
            reranker=reranker,  # type: ignore[arg-type]
        ),
        explainer=explainer,  # type: ignore[arg-type]
    )


def _answer_conceptually(
    pipeline: AnswerPipeline,
    repository_id: str,
    case: QueryCase,
    *,
    record_timings: bool,
) -> QueryPrediction:
    started = time.perf_counter()
    try:
        result = pipeline.execute(
            AnswerRequest(
                repository_id=repository_id,
                question=case.question,
                request_id=f"eval_{case.id}",
            )
        )
    except CodeAtlasError:
        return _abstention(case)

    response = result.response
    duration_ms = (time.perf_counter() - started) * 1000 if record_timings else 0.0
    return QueryPrediction(
        case_id=case.id,
        ranked_symbols=[
            item.symbol for item in response.evidence if item.symbol is not None
        ],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id=item.evidence_id,
                snapshot_id=case.snapshot_id,
                file_path=item.file_path,
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in response.evidence
        ],
        relation_paths=[
            " -> ".join(step.target for step in path.steps)
            for path in response.relation_paths
        ],
        claims=[claim.text for claim in response.answer.claims],
        abstained=not response.evidence,
        duration_ms=duration_ms,
        answer_summary=response.answer.summary,
    )


class EvaluationAdapterError(RuntimeError):
    """The harness could not produce a measurement it would stand behind."""


# --- Phase 4: change prediction -----------------------------------------------

# How the corpus labels a symbol, when that differs from the engine's qualified
# name. Two conventions, both read off the declared cases:
#
# * a `docs_config` document section carries a file-stem prefix
#   (`README.Health`) while `mixed_app`'s sections carry none (`Order flow`).
#   No uniqueness rule explains the difference; it is a corpus quirk, recorded
#   in the PLAN.md handoff, and the corpus is not edited to tidy it.
# * a configuration key is labeled by the dotted leaf path whose value changed,
#   while being cited at its top-level block's range. P4-05 gave YAML the
#   nested dotted paths that make this derivable.
_STEM_PREFIXED_FIXTURES: Final[frozenset[str]] = frozenset({"docs_config"})


def predict_changes(
    dataset: Dataset,
    *,
    record_timings: bool = True,
) -> PredictionFile:
    """Run every declared change case through the real engine.

    Each case is two directories — the variant overlays P4-02 authored — so this
    exercises the same `ChangeAnalysisEngine` the product flows use, with no Git
    and no database in the way. A case the engine cannot run is emitted as an
    empty prediction rather than skipped: "found nothing" and "was not measured"
    must not be the same number at a gate.
    """
    engine = ChangeAnalysisEngine()
    predictions: list[ChangePrediction] = []

    with tempfile.TemporaryDirectory(prefix="codeatlas-change-") as workspace:
        staging = Path(workspace)
        for index, case in enumerate(dataset.change_cases):
            base = _materialize(staging / f"{index}-base", case.base_state)
            target = _materialize(
                staging / f"{index}-target", case.target_state
            )

            started = time.perf_counter()
            try:
                report = engine.analyze(
                    DirectoryStateView(base), DirectoryStateView(target)
                )
            except CodeAtlasError:
                predictions.append(_empty_change(case.id))
                continue

            duration = (
                (time.perf_counter() - started) * 1000 if record_timings else 0.0
            )
            predictions.append(_change_prediction(case, report, duration))

    return PredictionFile(
        implementation_status="implemented",
        query_predictions=[],
        change_predictions=predictions,
    )


def _change_prediction(
    case: ChangeCase, report: ChangeReport, duration_ms: float
) -> ChangePrediction:
    label = _labeler(case, report)
    evidence, findings = _change_evidence(case, report)
    return ChangePrediction(
        case_id=case.id,
        changed_symbols=[
            label(item.qualified_name) for item in report.changed_symbols
        ],
        impact_paths=[
            [label(source), label(target)] for source, target in report.impact.paths
        ],
        findings=findings,
        evidence=evidence,
        claims=[],
        duration_ms=duration_ms,
    )


def _labeler(
    case: ChangeCase, report: ChangeReport
) -> Callable[[str], str]:
    """Map an engine qualified name onto the label the corpus uses."""
    stem_prefixed = case.repository_fixture in _STEM_PREFIXED_FIXTURES
    sections: dict[str, str] = {}
    config: dict[str, str] = {}

    state = report.target or report.base
    if state is not None:
        for symbol in state.graph.symbols.values():
            if symbol.kind is SymbolKind.DOCUMENT_SECTION and stem_prefixed:
                path = state.graph.file_paths.get(symbol.file_id, "")
                stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                if stem:
                    sections[symbol.qualified_name] = (
                        f"{stem}.{symbol.qualified_name}"
                    )
            elif symbol.kind is SymbolKind.CONFIG_KEY:
                dotted = [
                    part.strip()
                    for part in symbol.module_path.split(",")
                    if part.strip() and "." in part
                ]
                if dotted:
                    config[symbol.qualified_name] = dotted[0]

    # A configuration key is labeled by the nested path the corpus names, when
    # the corpus names one; otherwise its own name stands.
    declared = set(case.expected_changed_symbols) | {
        name for path in case.expected_impact_paths for name in path
    }
    for name, fallback in list(config.items()):
        candidates = [item for item in declared if item.startswith(f"{name}.")]
        config[name] = candidates[0] if candidates else fallback

    def label(name: str) -> str:
        return sections.get(name) or config.get(name) or name

    return label


def _change_evidence(
    case: ChangeCase, report: ChangeReport
) -> tuple[list[EvidencePrediction], list[FindingPrediction]]:
    """Cite each finding's subject at the range the engine recorded for it.

    The dataset's declared snapshot label is applied for comparison with the
    gold corpus; the range itself comes from the engine and nowhere else.
    """
    by_name = {item.qualified_name: item for item in report.changed_symbols}
    # The corpus has two base-side labeling conventions: most fixtures suffix
    # the snapshot (`python-v1` / `python-v1-base`), while `git_changes` names
    # the sides outright (`git-base` / `git-target`). Both are read off the
    # declared evidence rows, never invented.
    if case.snapshot_id.endswith("-target"):
        base_label = case.snapshot_id[: -len("-target")] + "-base"
    else:
        base_label = f"{case.snapshot_id}-base"
    evidence: dict[str, EvidencePrediction] = {}
    findings: list[FindingPrediction] = []

    for index, draft in enumerate(report.findings):
        if draft.code == "FILE_RENAMED":
            # The rename's proof is the pairing symbol seen on both sides.
            pair = next(
                (
                    item
                    for item in report.changed_files
                    if item.kind is FileChangeKind.RENAMED
                    and item.path == draft.subject
                ),
                None,
            )
            mover = next(
                (
                    item
                    for item in report.changed_symbols
                    if pair is not None
                    and item.file_path == pair.path
                    and item.base_file_path == pair.base_path
                ),
                None,
            )
            if (
                mover is None
                or mover.base_file_path is None
                or mover.base_start_line is None
                or mover.base_end_line is None
                or mover.target_start_line is None
                or mover.target_end_line is None
            ):
                continue
            base_id = f"{case.id}-p{index}a"
            target_id = f"{case.id}-p{index}b"
            evidence[base_id] = EvidencePrediction(
                evidence_id=base_id,
                snapshot_id=base_label,
                file_path=case.base_state.label_prefix + mover.base_file_path,
                start_line=mover.base_start_line,
                end_line=mover.base_end_line,
            )
            evidence[target_id] = EvidencePrediction(
                evidence_id=target_id,
                snapshot_id=case.snapshot_id,
                file_path=case.target_state.label_prefix + mover.file_path,
                start_line=mover.target_start_line,
                end_line=mover.target_end_line,
            )
            findings.append(
                FindingPrediction(
                    code=draft.code, evidence_ids=[base_id, target_id]
                )
            )
            continue

        change = by_name.get(draft.subject)
        if change is None:
            continue
        deleted = change.change_kind is ChangeKind.DELETED
        if deleted or draft.side is AnalysisSide.BASE:
            path = change.base_file_path or change.file_path
            start, end = change.base_start_line, change.base_end_line
            snapshot = base_label
            # The engine reports state-root-relative paths; the corpus labels
            # `git_changes` files by their side directory (`base/service.py`).
            path = case.base_state.label_prefix + path
        else:
            path = case.target_state.label_prefix + change.file_path
            start, end = change.target_start_line, change.target_end_line
            # The precise span proves the statement-level classes and the
            # binding change; a signature or export finding is about the whole
            # definition and keeps the full symbol range (c003 vs c002).
            if change.evidence_start_line is not None and draft.code in {
                "RETURN_VALUE_CHANGED",
                "ERROR_BEHAVIOR_CHANGED",
                "DEPENDENCY_CHANGED",
            }:
                start = change.evidence_start_line
                end = change.evidence_end_line
            snapshot = case.snapshot_id
        if start is None or end is None:
            continue

        evidence_id = f"{case.id}-p{index}"
        evidence[evidence_id] = EvidencePrediction(
            evidence_id=evidence_id,
            snapshot_id=snapshot,
            file_path=path,
            start_line=start,
            end_line=end,
        )
        findings.append(
            FindingPrediction(code=draft.code, evidence_ids=[evidence_id])
        )

    return list(evidence.values()), findings


def _empty_change(case_id: str) -> ChangePrediction:
    return ChangePrediction(
        case_id=case_id,
        changed_symbols=[],
        impact_paths=[],
        findings=[],
        evidence=[],
        claims=[],
        duration_ms=0.0,
    )


def _materialize(destination: Path, spec: StateSpec) -> Path:
    """Build one side of a change: the spec's root with its overlay applied.

    An overlay holds only the files that differ, so it cannot stand alone — used
    by itself, every file the overlay omits reads as deleted and the diff is
    nonsense. The state root is copied first and the overlay written over it,
    which is what decision 12's "the absent side defaults to the fixture root"
    means in practice. For the `git_changes` fixture the root is the *selected*
    side directory, never the merged fixture root: the engine must not see both
    sides of the fixture inside one state.

    A file the overlay declares empty is a deletion: there is no other way to
    express "this file is gone on this side" in a directory of files.
    """
    shutil.copytree(spec.root, destination)
    if spec.overlay is not None:
        for source in sorted(spec.overlay.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(spec.overlay)
            landing = destination / relative
            landing.parent.mkdir(parents=True, exist_ok=True)
            if source.stat().st_size == 0:
                landing.unlink(missing_ok=True)
            else:
                shutil.copy2(source, landing)
    return destination
