"""Deterministic Phase 0 evaluation metrics and report rendering."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import Field, model_validator

from codeatlas.contracts import (
    Confidence,
    ContractModel,
    NonEmptyText,
    NonNegativeDuration,
    OpaqueId,
    PositiveLine,
    RepositoryRelativePath,
)
from codeatlas.evaluation.dataset import (
    DATASET_CONTRACT_VERSION,
    LEXICAL_INTENTS,
    SYMBOL_INTENTS,
    ChangeCase,
    Dataset,
    QueryCase,
    TargetProfile,
)


class EvaluationError(ValueError):
    """Predictions do not conform to the selected evaluation dataset."""


class _EvidenceLike(Protocol):
    snapshot_id: str
    file_path: str
    start_line: int
    end_line: int


class EvidencePrediction(ContractModel):
    evidence_id: OpaqueId
    snapshot_id: OpaqueId
    file_path: RepositoryRelativePath
    start_line: PositiveLine
    end_line: PositiveLine

    @model_validator(mode="after")
    def validate_range(self) -> EvidencePrediction:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class QueryPrediction(ContractModel):
    case_id: OpaqueId
    ranked_symbols: list[NonEmptyText]
    ranked_evidence: list[EvidencePrediction]
    relation_paths: list[NonEmptyText]
    claims: list[NonEmptyText]
    abstained: bool
    duration_ms: NonNegativeDuration
    # Did the adapter actually run this case? A case outside the adapter's
    # declared scope is emitted as an abstention, and an abstention that was
    # never attempted is not a wrong answer -- `engine_adapter` says in its own
    # docstring that "not implemented" and "answered wrongly" are different
    # facts and the baseline must not blur them. Scoring blurred them anyway,
    # putting an unreachable ceiling on any metric containing such a case
    # (ADR-0024). Defaults to True so an existing prediction file parses
    # unchanged and every case in it stays scored exactly as before.
    measured: bool = True
    # Additive and optional, so `contract_version` stays "1.0" and an existing
    # prediction file parses unchanged (the ADR-0004 precedent). No metric reads
    # it: the scored suite is computed from evidence and claims. It exists so
    # the explanation A/B can check a *model-written* summary against a case's
    # forbidden claims — the one surface generation can introduce an
    # unsupported statement on, and one the structured claims cannot cover
    # because a model never writes them.
    answer_summary: str = ""


class FindingPrediction(ContractModel):
    code: NonEmptyText
    evidence_ids: list[OpaqueId] = Field(min_length=1)


class ChangePrediction(ContractModel):
    case_id: OpaqueId
    changed_symbols: list[NonEmptyText]
    impact_paths: list[list[NonEmptyText]]
    findings: list[FindingPrediction]
    evidence: list[EvidencePrediction]
    claims: list[NonEmptyText]
    duration_ms: NonNegativeDuration

    @model_validator(mode="after")
    def validate_finding_evidence(self) -> ChangePrediction:
        evidence_ids = [item.evidence_id for item in self.evidence]
        _ensure_unique(evidence_ids, "change evidence IDs")
        known = set(evidence_ids)
        for finding in self.findings:
            if set(finding.evidence_ids) - known:
                raise ValueError("finding references unknown evidence")
        return self


class PredictionFile(ContractModel):
    contract_version: Literal["1.0"] = DATASET_CONTRACT_VERSION
    implementation_status: Literal["implemented", "not_implemented"] = (
        "implemented"
    )
    query_predictions: list[QueryPrediction] = Field(default_factory=list)
    change_predictions: list[ChangePrediction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> PredictionFile:
        _ensure_unique(
            [item.case_id for item in self.query_predictions],
            "query prediction IDs",
        )
        _ensure_unique(
            [item.case_id for item in self.change_predictions],
            "change prediction IDs",
        )
        return self


class RankedMetrics(ContractModel):
    recall: Confidence
    reciprocal_rank: Confidence
    ndcg: Confidence


class QueryScore(ContractModel):
    case_id: OpaqueId
    measured: bool = True
    exact_symbol_resolved: bool | None
    symbols: RankedMetrics
    evidence: RankedMetrics
    # ADR-0003 granularity, reported beside `evidence` rather than replacing
    # it. `evidence` keeps requiring an exact span; this one asks whether the
    # citation covers the answer.
    evidence_containing: RankedMetrics
    valid_evidence_count: int = Field(ge=0)
    containing_evidence_count: int = Field(ge=0)
    predicted_evidence_count: int = Field(ge=0)
    relation_path_correctness: Confidence
    # ADR-0038. Precision penalises the engine for emitting a true edge the
    # corpus did not declare -- which ADR-0020 *requires* it to do. Recall asks
    # the question the corpus can actually answer: did every declared relation
    # appear? The precision number is retained unchanged so no tracked baseline
    # changes meaning, the treatment ADR-0003 gave `valid_evidence_rate`.
    relation_path_recall: Confidence = 0.0
    forbidden_claim_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    abstention_correct: bool
    duration_ms: NonNegativeDuration


class ChangeScore(ContractModel):
    case_id: OpaqueId
    changed_symbol_precision: Confidence
    changed_symbol_recall: Confidence
    direct_impact_recall: Confidence | None
    finding_precision: Confidence
    evidence_recall: Confidence
    # The change-side counterpart of `QueryScore.evidence_containing`. Both
    # sides feed one aggregate, so both must use the same rule or the number
    # would mean two things at once.
    evidence_containing_recall: Confidence
    # Whether the engine emitted the *same number* of each finding code the
    # case declares, not merely the same set. `expected_findings` was compared
    # as a set, and a set cannot count -- which is why c012 emitted two
    # `CONFIG_VALUE_CHANGED` findings for one edit from Phase 4 until
    # 2026-08-11 with no metric ever seeing it (ADR-0042). Reported beside
    # `finding_precision` rather than replacing it, so no existing number
    # changes meaning (the ADR-0038 pattern).
    finding_count_correct: bool
    valid_evidence_count: int = Field(ge=0)
    containing_evidence_count: int = Field(ge=0)
    predicted_evidence_count: int = Field(ge=0)
    forbidden_claim_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    duration_ms: NonNegativeDuration


MetricValue = float | None


class AggregateMetrics(ContractModel):
    # Scoped to symbol-shaped intents (ADR-0023). A lexical question is
    # answered by matching text, so scoring it as a top-1 *symbol* result
    # asked something other than what was posed, and blended two different
    # questions into one number.
    exact_symbol_resolution: MetricValue
    # Defaulted so an artifact written before ADR-0023 still loads.
    lexical_resolution: MetricValue = None
    symbol_recall_at_10: MetricValue
    mean_reciprocal_rank: MetricValue
    ndcg_at_10: MetricValue
    primary_evidence_recall_at_10: MetricValue
    # ADR-0003 granularity applied to recall. Defaulted to `None` so an
    # artifact written before this record still loads and is scored exactly as
    # it was. `primary_evidence_recall_at_10` is retained and unchanged, so no
    # historical number changes meaning -- the same treatment ADR-0003 gave
    # `valid_evidence_rate` when `containing_evidence_rate` arrived.
    containing_evidence_recall_at_10: MetricValue = None
    valid_evidence_rate: MetricValue
    # ADR-0003. `valid_evidence_rate` is retained and equals
    # `exact_evidence_rate`, so no historical number changes meaning. The two
    # rates are reported side by side because the gap between them is itself
    # the measurement: it says how precisely CodeAtlas can point at an answer.
    exact_evidence_rate: MetricValue
    containing_evidence_rate: MetricValue
    relation_path_correctness: MetricValue
    # ADR-0038. Defaulted to `None` so an artifact written before this record
    # still loads and is scored exactly as it was, the same treatment
    # `containing_evidence_recall_at_10` got from ADR-0027.
    relation_path_recall: MetricValue = None
    changed_symbol_precision: MetricValue
    changed_symbol_recall: MetricValue
    direct_impact_recall: MetricValue
    finding_precision: MetricValue
    # The fraction of change cases where every finding code was emitted the
    # number of times the case declares. Defaulted to None and reported
    # beside `finding_precision`, never replacing it, so no tracked baseline
    # changes meaning (ADR-0038's pattern). Ungated for now: the corpus
    # declares codes, not counts, so a low number today measures the corpus
    # rather than the engine.
    finding_count_correctness: MetricValue = None
    unsupported_claim_rate: MetricValue
    abstention_correctness: MetricValue
    total_duration_ms: float = Field(ge=0.0)


class EvaluationReport(ContractModel):
    contract_version: Literal["1.0"] = DATASET_CONTRACT_VERSION
    implementation_status: Literal["implemented", "not_implemented"]
    case_counts: dict[str, int]
    metrics: AggregateMetrics
    targets_met: bool
    unmet_targets: list[str]


def ranked_metrics(
    required: Iterable[str],
    ranked: Iterable[str],
    *,
    limit: int,
) -> RankedMetrics:
    """Calculate binary-relevance Recall@K, reciprocal rank, and nDCG@K."""
    required_set = set(required)
    ranked_items = list(dict.fromkeys(ranked))[:limit]
    if not required_set:
        empty_success = 1.0 if not ranked_items else 0.0
        return RankedMetrics(
            recall=empty_success,
            reciprocal_rank=empty_success,
            ndcg=empty_success,
        )

    relevant_ranks = [
        index
        for index, item in enumerate(ranked_items, start=1)
        if item in required_set
    ]
    recall = len({item for item in ranked_items if item in required_set}) / len(
        required_set
    )
    reciprocal_rank = 0.0 if not relevant_ranks else 1.0 / relevant_ranks[0]
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal_count = min(len(required_set), limit)
    idcg = sum(
        1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1)
    )
    return RankedMetrics(
        recall=recall,
        reciprocal_rank=reciprocal_rank,
        ndcg=0.0 if idcg == 0 else dcg / idcg,
    )


def contains_forbidden_claim(
    claim: str,
    forbidden_claims: Iterable[str],
) -> bool:
    normalized_claim = _normalize_claim(claim)
    return any(
        _normalize_claim(forbidden) in normalized_claim
        for forbidden in forbidden_claims
    )


def score_query_case(
    case: QueryCase,
    prediction: QueryPrediction,
) -> QueryScore:
    if prediction.case_id != case.id:
        raise EvaluationError("query prediction case_id does not match case")
    symbol_metrics = ranked_metrics(
        case.expected_symbols, prediction.ranked_symbols, limit=10
    )
    evidence_required = [_evidence_key(item) for item in case.expected_evidence]
    evidence_ranked = [
        _prediction_evidence_key(item)
        for item in prediction.ranked_evidence
    ]
    evidence_metrics = ranked_metrics(
        evidence_required, evidence_ranked, limit=10
    )
    evidence_containing_metrics = ranked_metrics(
        evidence_required,
        _containment_keys(prediction.ranked_evidence, case.expected_evidence),
        limit=10,
    )
    valid_evidence = sum(
        item in set(evidence_required) for item in evidence_ranked
    )
    containing_evidence = _containing_count(
        prediction.ranked_evidence, case.expected_evidence
    )
    expected_relations = set(case.expected_relations)
    predicted_relations = set(prediction.relation_paths)
    relation_correctness = _precision(predicted_relations, expected_relations)
    relation_recall = _recall(predicted_relations, expected_relations)
    forbidden_count = sum(
        contains_forbidden_claim(claim, case.forbidden_claims)
        for claim in prediction.claims
    )
    exact = (
        None
        if not case.expected_symbols or not prediction.measured
        else bool(prediction.ranked_symbols)
        and prediction.ranked_symbols[0] in set(case.expected_symbols)
    )
    return QueryScore(
        case_id=case.id,
        measured=prediction.measured,
        exact_symbol_resolved=exact,
        symbols=symbol_metrics,
        evidence=evidence_metrics,
        evidence_containing=evidence_containing_metrics,
        valid_evidence_count=valid_evidence,
        containing_evidence_count=containing_evidence,
        predicted_evidence_count=len(evidence_ranked),
        relation_path_correctness=relation_correctness,
        relation_path_recall=relation_recall,
        forbidden_claim_count=forbidden_count,
        claim_count=len(prediction.claims),
        abstention_correct=prediction.abstained == case.expected_abstention,
        duration_ms=prediction.duration_ms,
    )


def score_change_case(
    case: ChangeCase,
    prediction: ChangePrediction,
) -> ChangeScore:
    if prediction.case_id != case.id:
        raise EvaluationError("change prediction case_id does not match case")
    expected_symbols = set(case.expected_changed_symbols)
    predicted_symbols = set(prediction.changed_symbols)
    expected_paths = {_path_key(path) for path in case.expected_impact_paths}
    predicted_paths = {_path_key(path) for path in prediction.impact_paths}
    expected_findings = set(case.expected_findings)
    expected_evidence = {
        _evidence_key(item)
        for item in case.expected_evidence
    }
    predicted_evidence_by_id = {
        item.evidence_id: _prediction_evidence_key(item)
        for item in prediction.evidence
    }
    predicted_evidence = list(predicted_evidence_by_id.values())
    supported_finding_codes = [
        finding.code
        for finding in prediction.findings
        if all(
            predicted_evidence_by_id[evidence_id] in expected_evidence
            for evidence_id in finding.evidence_ids
        )
    ]
    supported_findings = set(supported_finding_codes)
    # Multiset, so a repeated code is a different answer from a single one.
    finding_count_correct = Counter(supported_finding_codes) == Counter(
        case.expected_findings
    )
    forbidden_count = sum(
        contains_forbidden_claim(claim, case.forbidden_claims)
        for claim in prediction.claims
    )
    return ChangeScore(
        case_id=case.id,
        changed_symbol_precision=_precision(
            predicted_symbols, expected_symbols
        ),
        changed_symbol_recall=_recall(predicted_symbols, expected_symbols),
        direct_impact_recall=(
            _recall(predicted_paths, expected_paths)
            if expected_paths
            else None
        ),
        finding_precision=_precision(
            supported_findings, expected_findings
        ),
        finding_count_correct=finding_count_correct,
        evidence_recall=_recall(
            set(predicted_evidence), expected_evidence
        ),
        evidence_containing_recall=_recall(
            set(_containment_keys(prediction.evidence, case.expected_evidence)),
            expected_evidence,
        ),
        valid_evidence_count=sum(
            item in expected_evidence for item in predicted_evidence
        ),
        containing_evidence_count=_containing_count(
            prediction.evidence, case.expected_evidence
        ),
        predicted_evidence_count=len(predicted_evidence),
        forbidden_claim_count=forbidden_count,
        claim_count=len(prediction.claims),
        duration_ms=prediction.duration_ms,
    )


def null_baseline(dataset: Dataset) -> EvaluationReport:
    metrics = AggregateMetrics(
        exact_symbol_resolution=0.0,
        symbol_recall_at_10=0.0,
        mean_reciprocal_rank=0.0,
        ndcg_at_10=0.0,
        primary_evidence_recall_at_10=0.0,
        # Explicitly 0.0, not the field's `None` default. The null baseline
        # asserts "nothing is implemented, so nothing is found"; leaving this
        # unset would say "not measured", which is a different claim and the
        # exact distinction ADR-0024 exists to keep.
        containing_evidence_recall_at_10=0.0,
        valid_evidence_rate=None,
        exact_evidence_rate=None,
        containing_evidence_rate=None,
        relation_path_correctness=0.0,
        # Explicitly 0.0, not the field's `None` default, for the reason the
        # `containing_evidence_recall_at_10` comment above gives: the null
        # baseline asserts "nothing is implemented, so nothing is found", and
        # leaving it unset would say "not measured" -- a different claim.
        relation_path_recall=0.0,
        changed_symbol_precision=0.0,
        changed_symbol_recall=0.0,
        direct_impact_recall=0.0,
        finding_precision=0.0,
        unsupported_claim_rate=None,
        abstention_correctness=None,
        total_duration_ms=0.0,
    )
    unmet_targets = _unmet_targets(metrics, "retrieval")
    return EvaluationReport(
        implementation_status="not_implemented",
        case_counts={
            "queries": len(dataset.query_cases),
            "changes": len(dataset.change_cases),
        },
        metrics=metrics,
        targets_met=not unmet_targets,
        unmet_targets=unmet_targets,
    )


def evaluate_predictions(
    dataset: Dataset,
    predictions: PredictionFile,
) -> EvaluationReport:
    return _evaluate(dataset, predictions)


def render_markdown(report: EvaluationReport) -> str:
    rows = [
        ("Query cases", str(report.case_counts["queries"])),
        ("Change cases", str(report.case_counts["changes"])),
        (
            "Exact symbol resolution",
            _format_metric(report.metrics.exact_symbol_resolution),
        ),
        (
            "Primary evidence Recall@10",
            _format_metric(report.metrics.primary_evidence_recall_at_10),
        ),
        (
            "Containing evidence Recall@10",
            _format_metric(report.metrics.containing_evidence_recall_at_10),
        ),
        (
            "Valid evidence rate",
            _format_metric(report.metrics.valid_evidence_rate),
        ),
        (
            "Exact evidence rate",
            _format_metric(report.metrics.exact_evidence_rate),
        ),
        (
            "Containing evidence rate",
            _format_metric(report.metrics.containing_evidence_rate),
        ),
        (
            "Changed-symbol precision",
            _format_metric(report.metrics.changed_symbol_precision),
        ),
        (
            "Changed-symbol recall",
            _format_metric(report.metrics.changed_symbol_recall),
        ),
        (
            "Direct-impact recall",
            _format_metric(report.metrics.direct_impact_recall),
        ),
        (
            "Unsupported-claim rate",
            _format_metric(report.metrics.unsupported_claim_rate),
        ),
    ]
    body = "\n".join(f"| {label} | {value} |" for label, value in rows)
    unmet = (
        ", ".join(report.unmet_targets)
        if report.unmet_targets
        else "None"
    )
    return (
        "# CodeAtlas Evaluation Report\n\n"
        f"- Contract version: `{report.contract_version}`\n"
        f"- Implementation status: `{report.implementation_status}`\n"
        f"- Targets met: `{str(report.targets_met).lower()}`\n"
        f"- Unmet targets: {unmet}\n\n"
        "| Metric | Value |\n"
        "| --- | ---: |\n"
        f"{body}\n"
    )


def _evaluate(
    dataset: Dataset,
    predictions: PredictionFile,
) -> EvaluationReport:
    query_cases = {case.id: case for case in dataset.query_cases}
    change_cases = {case.id: case for case in dataset.change_cases}
    query_predictions = {
        item.case_id: item for item in predictions.query_predictions
    }
    change_predictions = {
        item.case_id: item for item in predictions.change_predictions
    }
    unknown_queries = query_predictions.keys() - query_cases.keys()
    unknown_changes = change_predictions.keys() - change_cases.keys()
    if unknown_queries or unknown_changes:
        raise EvaluationError("predictions reference unknown case IDs")

    query_scores = [
        score_query_case(
            case,
            query_predictions.get(case.id, _empty_query_prediction(case.id)),
        )
        for case in dataset.query_cases
    ]
    change_scores = [
        score_change_case(
            case,
            change_predictions.get(
                case.id, _empty_change_prediction(case.id)
            ),
        )
        for case in dataset.change_cases
    ]
    metrics = _aggregate(query_scores, change_scores, dataset)
    unmet_targets = _unmet_targets(metrics, dataset.target_profile)
    return EvaluationReport(
        implementation_status=predictions.implementation_status,
        case_counts={
            "queries": len(dataset.query_cases),
            "changes": len(dataset.change_cases),
        },
        metrics=metrics,
        targets_met=not unmet_targets,
        unmet_targets=unmet_targets,
    )


def _aggregate(
    query_scores: list[QueryScore],
    change_scores: list[ChangeScore],
    dataset: Dataset,
) -> AggregateMetrics:
    def _top1(intents: frozenset[str]) -> list[float]:
        return [
            float(score.exact_symbol_resolved)
            for score, case in zip(query_scores, dataset.query_cases, strict=True)
            if score.exact_symbol_resolved is not None and case.intent in intents
        ]

    exact = _top1(SYMBOL_INTENTS)
    lexical = _top1(LEXICAL_INTENTS)
    symbol_scores = [
        score.symbols
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_symbols and score.measured
    ]
    query_evidence_recall = [
        score.evidence.recall
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_evidence and score.measured
    ]
    change_evidence_recall = [
        score.evidence_recall
        for score, case in zip(
            change_scores, dataset.change_cases, strict=True
        )
        if case.expected_evidence
    ]
    query_containing_recall = [
        score.evidence_containing.recall
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_evidence and score.measured
    ]
    change_containing_recall = [
        score.evidence_containing_recall
        for score, case in zip(
            change_scores, dataset.change_cases, strict=True
        )
        if case.expected_evidence
    ]
    relation_scores = [
        score.relation_path_correctness
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_relations and score.measured
    ]
    relation_recall_scores = [
        score.relation_path_recall
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_relations and score.measured
    ]
    impact_recall = [
        score.direct_impact_recall
        for score in change_scores
        if score.direct_impact_recall is not None
    ]
    predicted_evidence = sum(
        score.predicted_evidence_count for score in query_scores
    ) + sum(score.predicted_evidence_count for score in change_scores)
    valid_evidence = sum(
        score.valid_evidence_count for score in query_scores
    ) + sum(score.valid_evidence_count for score in change_scores)
    containing_evidence = sum(
        score.containing_evidence_count for score in query_scores
    ) + sum(score.containing_evidence_count for score in change_scores)
    claim_count = sum(score.claim_count for score in query_scores) + sum(
        score.claim_count for score in change_scores
    )
    forbidden_count = sum(
        score.forbidden_claim_count for score in query_scores
    ) + sum(score.forbidden_claim_count for score in change_scores)
    return AggregateMetrics(
        exact_symbol_resolution=_mean(exact),
        lexical_resolution=_mean(lexical),
        symbol_recall_at_10=_mean(
            [score.recall for score in symbol_scores]
        ),
        mean_reciprocal_rank=_mean(
            [score.reciprocal_rank for score in symbol_scores]
        ),
        ndcg_at_10=_mean([score.ndcg for score in symbol_scores]),
        primary_evidence_recall_at_10=_mean(
            [*query_evidence_recall, *change_evidence_recall]
        ),
        containing_evidence_recall_at_10=_mean(
            [*query_containing_recall, *change_containing_recall]
        ),
        valid_evidence_rate=(
            valid_evidence / predicted_evidence
            if predicted_evidence
            else None
        ),
        exact_evidence_rate=(
            valid_evidence / predicted_evidence
            if predicted_evidence
            else None
        ),
        containing_evidence_rate=(
            containing_evidence / predicted_evidence
            if predicted_evidence
            else None
        ),
        relation_path_correctness=_mean(relation_scores),
        relation_path_recall=_mean(relation_recall_scores),
        changed_symbol_precision=_mean(
            [score.changed_symbol_precision for score in change_scores]
        ),
        changed_symbol_recall=_mean(
            [score.changed_symbol_recall for score in change_scores]
        ),
        direct_impact_recall=_mean(impact_recall),
        finding_precision=_mean(
            [score.finding_precision for score in change_scores]
        ),
        finding_count_correctness=_mean(
            [
                1.0 if score.finding_count_correct else 0.0
                for score in change_scores
            ]
        ),
        unsupported_claim_rate=(
            forbidden_count / claim_count if claim_count else None
        ),
        # An unmeasured case abstained because the adapter declined to run it,
        # not because the engine judged the evidence insufficient. Counting it
        # as a correct abstention would credit the engine for a decision it
        # never made.
        abstention_correctness=_mean(
            [
                float(score.abstention_correct)
                for score in query_scores
                if score.measured
            ]
        ),
        total_duration_ms=sum(
            score.duration_ms for score in query_scores
        )
        + sum(score.duration_ms for score in change_scores),
    )


def _unmet_targets(
    metrics: AggregateMetrics,
    profile: TargetProfile,
) -> list[str]:
    """Which gates a report misses, chosen by the corpus's declared profile.

    One table applied to every dataset held a 14-case corpus of deliberately
    fuzzy questions to a 0.98 top-1 rule written for exact symbol lookup, and
    reported the mismatch as an engine defect for four phases (ADR-0023). A
    corpus now declares which instrument it is.
    """
    minimums: dict[str, tuple[MetricValue, float]] = {
        "changed_symbol_precision": (metrics.changed_symbol_precision, 0.95),
        "changed_symbol_recall": (metrics.changed_symbol_recall, 0.95),
        "direct_impact_recall": (metrics.direct_impact_recall, 0.90),
        # The threshold is unchanged at 0.90 and the demand is unchanged --
        # "the answer's evidence must surface in the top 10". Only the
        # definition of *surfaced* is corrected per ADR-0003: requiring an
        # exact span gated on a granularity disagreement, not on whether the
        # evidence was found. `primary_evidence_recall_at_10` is still
        # reported beside it, because the gap between the two is the
        # measurement.
        "containing_evidence_recall_at_10": (
            metrics.containing_evidence_recall_at_10,
            0.90,
        ),
    }
    if profile == "retrieval":
        # `AGENTS.md` Section 19.3's declared product target, kept verbatim.
        #
        # **At this corpus size it enforces 27/27 and tolerates no failures**,
        # because 27 scored symbol-shaped cases can only produce 1.0000,
        # 0.9630, 0.9259, ... and 0.98 falls between the first two. The gate is
        # therefore stricter than the number reads (ADR-0033).
        #
        # That is deliberate, and the number is **not** changed to 1.0 the way
        # `lexical_resolution` was. 0.90 there was an internal provisional value
        # with no product meaning; 0.98 is a release commitment that becomes
        # expressible the moment the corpus reaches ~50 cases. Restating it as
        # 1.0 would tighten a product promise to match an artifact of corpus
        # size, and amending Section 19.3 to follow would edit the release
        # authority to suit the instrument.
        #
        # Being stricter than the target is safe: nothing violating 98% can
        # pass. The limitation is corpus size, and the fix is more cases.
        minimums["exact_symbol_resolution"] = (
            metrics.exact_symbol_resolution,
            0.98,
        )
        # 1.0, and the value is not a tightening (ADR-0032). The metric scores
        # eight cases -- ten declare a lexical intent, two sit on
        # `malicious_unsupported` and are excluded by ADR-0024 -- so it can only
        # take values that are multiples of 0.125. The provisional 0.90 it
        # replaces already required 8/8 and tolerated zero failures, selecting
        # exactly the same pass/fail set. Stating 1.0 says what the gate does
        # instead of reading as though a miss were acceptable.
        #
        # Absolute is also the right shape here: these are deterministic
        # lookups, and a config key or document heading either resolves or it
        # does not.
        minimums["lexical_resolution"] = (metrics.lexical_resolution, 1.0)
    else:
        # Top-1 is the wrong instrument for a conceptual question, so the
        # ranked measure replaces it: did the right answer surface at all.
        minimums["symbol_recall_at_10"] = (metrics.symbol_recall_at_10, 0.90)

    unmet = [
        name
        for name, (value, target) in minimums.items()
        if value is None or value < target
    ]
    # `containing_evidence_rate` is **deliberately not a gate condition**
    # (ADR-0048), and it is deliberately still computed and still reported.
    #
    # It is *precision*: containing / predicted over every evidence item the
    # engine emits. So it asks whether the engine emitted nothing beyond what
    # the corpus declared -- while **ADR-0020 requires every graph answer to
    # emit every supporting edge**, each of which carries evidence. An answer
    # citing five supporting locations against a case declaring one scores 1/5
    # for being complete.
    #
    # Measured 2026-08-16: crediting every remaining failing case reaches
    # 0.7724 against the old 1.00 target, leaving 28 items that are correct
    # supporting evidence no expectation declares. The gap cannot be closed by
    # improving the engine -- only by emitting less, which ADR-0020 forbids.
    #
    # This is ADR-0038's shape and its resolution: precision retained and
    # reported, recall gated. `containing_evidence_recall_at_10` keeps its 0.90
    # threshold above, because "did the evidence surface" does not penalise
    # completeness. The number stays because every tracked baseline carries it
    # and removing it would quietly change what those artifacts mean.
    if (
        metrics.unsupported_claim_rate is not None
        and metrics.unsupported_claim_rate >= 0.02
    ):
        unmet.append("unsupported_claim_rate")
    return unmet


def _empty_query_prediction(case_id: str) -> QueryPrediction:
    return QueryPrediction(
        case_id=case_id,
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=False,
        duration_ms=0.0,
    )


def _empty_change_prediction(case_id: str) -> ChangePrediction:
    return ChangePrediction(
        case_id=case_id,
        changed_symbols=[],
        impact_paths=[],
        findings=[],
        evidence=[],
        claims=[],
        duration_ms=0.0,
    )


def _evidence_key(item: _EvidenceLike) -> str:
    return (
        f"{item.snapshot_id}:{item.file_path}:{item.start_line}:{item.end_line}"
    )


def _prediction_evidence_key(item: EvidencePrediction) -> str:
    return (
        f"{item.snapshot_id}:{item.file_path}:{item.start_line}:{item.end_line}"
    )


def _contains(predicted: _EvidenceLike, expected: _EvidenceLike) -> bool:
    """Whether ``predicted`` fully covers ``expected`` in the same file.

    ADR-0003. Containment is directional and file-scoped. A prediction that
    merely overlaps — clipping either end of the expected range — satisfies
    neither metric, because a citation that omits part of the answer has not
    proven it.
    """
    return (
        predicted.snapshot_id == expected.snapshot_id
        and predicted.file_path == expected.file_path
        and predicted.start_line <= expected.start_line
        and predicted.end_line >= expected.end_line
    )


def _containment_keys(
    predicted: Iterable[_EvidenceLike],
    expected: Iterable[_EvidenceLike],
) -> list[str]:
    """Key each prediction by the expected range it contains, else by itself.

    Feeding these into `ranked_metrics` and `_recall` gives containment
    semantics with **one** definition of the ranking arithmetic. A parallel
    Recall@K implementation that happened to disagree about ties, duplicates,
    or the nDCG denominator would make the two evidence numbers
    incomparable — and the gap between them is itself the measurement
    (ADR-0003).

    A prediction containing no expected range keeps its own key, so it can
    never collide with a required one and is counted as a miss exactly as
    before.
    """
    expected_items = list(expected)
    keys: list[str] = []
    for item in predicted:
        match = next(
            (target for target in expected_items if _contains(item, target)),
            None,
        )
        keys.append(
            _evidence_key(match) if match is not None else _evidence_key(item)
        )
    return keys


def _containing_count(
    predicted: Iterable[_EvidenceLike],
    expected: Iterable[_EvidenceLike],
) -> int:
    """Count predictions that contain at least one expected range.

    Exact agreement implies containment, so this is never below the exact
    count for the same inputs.
    """
    expected_items = list(expected)
    return sum(
        any(_contains(item, target) for target in expected_items)
        for item in predicted
    )


def _path_key(path: Iterable[str]) -> str:
    return " -> ".join(path)


def _precision(predicted: set[str], expected: set[str]) -> float:
    if not predicted:
        return 1.0 if not expected else 0.0
    return len(predicted & expected) / len(predicted)


def _recall(predicted: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(predicted & expected) / len(expected)


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return None if not items else sum(items) / len(items)


def _normalize_claim(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return " ".join(normalized.split()).casefold()


def _format_metric(value: MetricValue) -> str:
    return "not applicable" if value is None else f"{value:.4f}"


def _ensure_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
