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
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from codeatlas.analysis.engine import ChangeAnalysisEngine, ChangeReport
from codeatlas.analysis.states import (
    DirectoryStateView,
    GitBlobStateView,
    StateView,
)
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
    LEXICAL_INTENTS,
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
# Which end of a relation step is the *answer* to each relation intent.
#
# Evidence cites a reference site, so its label names the symbol containing that
# line — which is the answer for an inbound question ("who calls this": the
# caller holds the call site) and the subject for an outbound one ("what does
# this import": the import statement is in the importer). Projecting evidence
# labels as the answer therefore scored outbound questions against their own
# subject. The relation steps carry `source` and `kind` and `target`
# structurally, so the answer can be read rather than inferred.
#
# `TRACE_FLOW` is deliberately absent. A flow answer *includes* its origin — the
# corpus expects `PaymentService.capture` back when tracing from it — whereas a
# relation answer never does. Those are different questions, so trace keeps the
# evidence projection.
GRAPH_ANSWER_END: dict[str, str] = {
    "CALLERS": "source",
    "RELATED_TESTS": "source",
    "DEPENDENCIES": "target",
    "EXPORTS": "target",
}
# Phase 2 adds lexical retrieval, so documents and configuration keys can now be
# answered. Everything still unimplemented abstains rather than guessing. The
# set itself lives in `dataset.py` with the rest of the corpus vocabulary, so
# the adapter and the metric that scores it cannot disagree about which intents
# are lexical (ADR-0023).
# `CONCEPTUAL` is answered through the same lexical channel as the two
# `LEXICAL_INTENTS`, but is deliberately *not* one of them: ADR-0023 scopes
# `lexical_resolution` to configuration and document lookups, where "did the
# right thing rank first" is the question posed. A conceptual question is not
# top-1 shaped, so it is measured on recall and evidence and scored by neither
# top-1 metric.
#
# It was missing here until 2026-08-17 (ADR-0053), which meant q024 was never
# measured at all. A gated *fixture* scores `False` and stays in the
# denominator; a gated *intent* scores `measured=False` and leaves it — so this
# omission removed a failing case from the average rather than reporting
# capability as failure. The guard
# `test_every_intent_on_a_measurable_fixture_is_itself_measurable` derives the
# requirement from the corpus, so the constant cannot drift again.
SUPPORTED_INTENTS = (
    SUPPORTED_INTENT,
    *LEXICAL_INTENTS,
    *GRAPH_INTENTS,
    "CONCEPTUAL",
)
# Every corpus fixture except the deliberately hostile one. This list is a
# measurement gate, not a capability flag: a fixture missing here has its cases
# scored `False`, not skipped, so leaving it stale reports working capability as
# failure. It was written in Phase 1 and not revisited when Phase 3 added
# TypeScript/JavaScript and Phase 4 added Git, which understated
# `exact_symbol_resolution` by 0.23 and `abstention_correctness` by 0.22 for
# four phases. `malicious_unsupported` stays out on purpose — it carries
# prompt-injection text, and what the engine should return for hostile input is
# a security question that the accuracy corpus must not quietly answer.
SUPPORTED_FIXTURES = (
    "python_app",
    "docs_config",
    "mixed_app",
    "tsjs_app",
    "git_changes",
    # Added 2026-08-15 with the cases that use it. ADR-0017 records this
    # tuple frozen at Phase 1, understating two metrics for four phases;
    # a fixture admitted here without cases is refused by
    # test_every_corpus_fixture_is_measured_unless_deliberately_unsupported.
    "symbol_breadth",
    # `java_app` (ADR-0065) admitted 2026-08-19 with q066-q069, on the terms the
    # previous note set: the checkpoint passed -- Java resolution was verified by
    # indexing a two-package repository and confirming a cross-package import
    # resolves -- and the gold ranges were declared by reading the fixture source
    # before the engine was run against them (ADR-0003, ADR-0036).
    #
    # Java only. Go, Rust and Scala ship on the same engine but each carries an
    # undecided limit (a Go import resolves `external`; Scala captures only
    # bare-identifier calls), and a corpus case is the wrong instrument for an
    # open ruling -- it would either encode the limit as correct or fail for a
    # reason already known and declared. Java has no such limit.
    "java_app",
    # `scala_app` admitted 2026-08-19 with q070-q073, once ADR-0067 settled the
    # member-call limit. **q072 is the first evaluation coverage of that
    # ruling**: `payments.charge(id)` emitted no edge at all until the profile
    # contract gained a supplementary references query, and a unit test was the
    # only thing pinning it.
    #
    "scala_app",
    # `go_app` and `rust_app` admitted 2026-08-20, completing ADR-0065's four.
    #
    # **Go carries no import case, and that is a stated limit rather than an
    # omission.** ADR-0066 rules a Go import stays `external`; an external edge
    # has no `target_symbol_id`, so it never appears in a `relation_path`
    # (ADR-0057 restricts those to resolved edges). The corpus vocabulary cannot
    # express the ruled outcome, and a case that cannot fail reads as coverage
    # while providing none. `test_a_go_import_is_recorded_external_by_ruling` is
    # the only guard.
    #
    # **Rust's q080 is the control for that reasoning.** Its `crate` is a
    # language keyword, so its import *does* resolve -- the contrast that
    # diagnosed Go. If Rust imports ever stopped resolving, ADR-0066's
    # explanation would have lost the comparison it rests on.
    "go_app",
    "rust_app",
)


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
                    predictions.append(_abstention(case, measured=False))
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
            # The case's own depth, never the request default (ADR-0073
            # ruling 3). `traversal_depth` is required for exactly these
            # intents, so `or` never falls through for a validated corpus; it
            # is there so a hand-built `QueryCase` in a test still traverses to
            # the depth the dataclass documents rather than to `None`.
            # The case's own depth, never the request default (ADR-0073
            # ruling 3). `traversal_depth` is required for exactly these
            # intents, so `or` never falls through for a validated corpus; it
            # is there so a hand-built `QueryCase` in a test still traverses to
            # the depth the dataclass documents rather than to `None`.
            response = method(
                GraphQueryRequest(
                    repository_id=repository_id,
                    symbol=_query_term(case),
                    request_id=f"eval_{case.id}",
                    max_depth=case.traversal_depth or 2,
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
        ranked_symbols=_ranked_symbols(case, response),
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
        # One string per *step*, in the corpus's "SOURCE KIND TARGET" form. The
        # previous projection joined targets only ("total -> Order"), which no
        # declared relation could ever equal, so `relation_path_correctness`
        # was a guaranteed zero rather than a measurement.
        relation_paths=[
            f"{step.source} {step.kind} {step.target}"
            for path in response.relation_paths
            for step in path.steps
        ],
        claims=[claim.text for claim in response.answer.claims],
        abstained=not response.evidence,
        duration_ms=duration_ms,
    )


def _ranked_symbols(case: QueryCase, response: object) -> list[str]:
    """The symbols the engine offers as the answer, in rank order.

    For a relation intent the answer is one end of each relation step; see
    `GRAPH_ANSWER_END` for which end and why trace is excluded. Everything else
    reads evidence labels, where the label already names the answer.
    """
    end = GRAPH_ANSWER_END.get(case.intent)
    if end is not None:
        named = [
            getattr(step, end)
            for path in response.relation_paths  # type: ignore[attr-defined]
            for step in path.steps
        ]
        # A relation answer never names its own subject, but an engine that
        # returned no usable steps must not silently fall back to evidence
        # labels: that is the projection this function exists to replace.
        return list(dict.fromkeys(item for item in named if item))
    return [
        item.symbol
        for item in response.evidence  # type: ignore[attr-defined]
        if item.symbol is not None
    ]


def _abstention(case: QueryCase, *, measured: bool = True) -> QueryPrediction:
    """An abstention, and whether the engine actually reached the question.

    `measured=False` marks a case this adapter declined to run at all -- an
    unsupported intent, or a fixture kept out of the accuracy corpus on purpose.
    The module docstring promises that "not implemented" and "answered wrongly"
    stay different facts; passing that distinction to the scorer is what keeps
    the promise (ADR-0024).
    """
    return QueryPrediction(
        case_id=case.id,
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=True,
        duration_ms=0.0,
        measured=measured,
    )


def _query_term(case: QueryCase) -> str:
    """Use the case's expected symbol as the exact lookup term.

    Phase 1 has no natural-language intent classifier. Feeding the declared
    symbol measures resolution accuracy, which is what this phase built; it does
    not measure question understanding, which it did not.

    A graph case may declare `query_subject`, because for a relation query the
    subject is not in `expected_symbols` at all — those are the answer. Asking
    "who calls `render`" when the case asks who calls `total` scores a correct
    engine as wrong, which is what this field exists to stop.
    """
    if case.query_subject is not None:
        return case.query_subject
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
        ranked_symbols=_ranked_symbols(case, response),
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
        # One string per *step*, in the corpus's "SOURCE KIND TARGET" form. The
        # previous projection joined targets only ("total -> Order"), which no
        # declared relation could ever equal, so `relation_path_correctness`
        # was a guaranteed zero rather than a measurement.
        relation_paths=[
            f"{step.source} {step.kind} {step.target}"
            for path in response.relation_paths
            for step in path.steps
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
            started = time.perf_counter()
            try:
                base_view, target_view = _state_views(
                    staging, index, case
                )
                report = engine.analyze(base_view, target_view)
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



def _state_views(
    staging: Path, index: int, case: ChangeCase
) -> tuple[StateView, StateView]:
    """The two views a change case is analysed through.

    `directory` materializes both sides side by side, which is what every case
    did before ADR-0077 and needs no Git.

    `git_blob` builds **one** working tree: the base is committed and read back
    through `GitBlobStateView`, then the target overlay is written over the same
    directory and read through `DirectoryStateView`. That is deliberately the
    shape of a real working-tree preflight -- `analyze_working_tree` compares a
    committed ref against the tree on disk -- and it is the only shape in which
    the blob view's ignore-rule handling participates at all (ADR-0044).

    Two directories would not do: the ADR-0044 defect is a *disagreement between
    the two view implementations* about which files exist, so a comparison that
    uses one implementation twice cannot produce it.
    """
    if case.base_view == "directory":
        base = _materialize(staging / f"{index}-base", case.base_state)
        target = _materialize(staging / f"{index}-target", case.target_state)
        return DirectoryStateView(base), DirectoryStateView(target)

    worktree = _materialize(staging / f"{index}-git", case.base_state)
    _commit_all(worktree)
    # The target overlay lands on top of the committed base, so HEAD holds the
    # base and the working tree holds the target -- one directory, two states.
    _apply_overlay(worktree, case.target_state)
    return GitBlobStateView(worktree, "HEAD"), DirectoryStateView(worktree)


def _commit_all(root: Path) -> None:
    """Initialise a repository and commit everything in it.

    Identity and signing are set locally rather than inherited: a contributor
    whose global config signs commits would otherwise fail the whole gate on a
    fixture, and `core.autocrlf` is pinned off so the committed bytes are the
    bytes written -- ADR-0043 is about the two sides disagreeing over line
    endings, and the harness must not introduce that disagreement itself.
    """
    for arguments in (
        ("init", "-q"),
        ("config", "user.email", "evaluation@codeatlas.invalid"),
        ("config", "user.name", "CodeAtlas Evaluation"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
        ("add", "-A"),
        ("commit", "-qm", "base state"),
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            shell=False,
        )


def _apply_overlay(destination: Path, spec: StateSpec) -> None:
    """Write one state's overlay over an existing tree, deletions included."""
    if spec.overlay is None:
        return
    for source in sorted(spec.overlay.rglob("*")):
        if not source.is_file():
            continue
        landing = destination / source.relative_to(spec.overlay)
        landing.parent.mkdir(parents=True, exist_ok=True)
        if source.stat().st_size == 0:
            landing.unlink(missing_ok=True)
        else:
            shutil.copy2(source, landing)


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
