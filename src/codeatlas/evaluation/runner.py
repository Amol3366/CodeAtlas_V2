"""Deterministic Phase 0 evaluation metrics and report rendering."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import Field, model_validator

from codeatlas.contracts import (
    CONTRACT_VERSION,
    Confidence,
    ContractModel,
    NonEmptyText,
    NonNegativeDuration,
    OpaqueId,
    PositiveLine,
    RepositoryRelativePath,
)
from codeatlas.evaluation.dataset import ChangeCase, Dataset, QueryCase


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
    contract_version: Literal["1.0"] = CONTRACT_VERSION
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
    exact_symbol_resolved: bool | None
    symbols: RankedMetrics
    evidence: RankedMetrics
    valid_evidence_count: int = Field(ge=0)
    predicted_evidence_count: int = Field(ge=0)
    relation_path_correctness: Confidence
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
    valid_evidence_count: int = Field(ge=0)
    predicted_evidence_count: int = Field(ge=0)
    forbidden_claim_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    duration_ms: NonNegativeDuration


MetricValue = float | None


class AggregateMetrics(ContractModel):
    exact_symbol_resolution: MetricValue
    symbol_recall_at_10: MetricValue
    mean_reciprocal_rank: MetricValue
    ndcg_at_10: MetricValue
    primary_evidence_recall_at_10: MetricValue
    valid_evidence_rate: MetricValue
    relation_path_correctness: MetricValue
    changed_symbol_precision: MetricValue
    changed_symbol_recall: MetricValue
    direct_impact_recall: MetricValue
    finding_precision: MetricValue
    unsupported_claim_rate: MetricValue
    abstention_correctness: MetricValue
    total_duration_ms: float = Field(ge=0.0)


class EvaluationReport(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
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
    valid_evidence = sum(
        item in set(evidence_required) for item in evidence_ranked
    )
    expected_relations = set(case.expected_relations)
    predicted_relations = set(prediction.relation_paths)
    relation_correctness = _precision(predicted_relations, expected_relations)
    forbidden_count = sum(
        contains_forbidden_claim(claim, case.forbidden_claims)
        for claim in prediction.claims
    )
    exact = (
        None
        if not case.expected_symbols
        else bool(prediction.ranked_symbols)
        and prediction.ranked_symbols[0] in set(case.expected_symbols)
    )
    return QueryScore(
        case_id=case.id,
        exact_symbol_resolved=exact,
        symbols=symbol_metrics,
        evidence=evidence_metrics,
        valid_evidence_count=valid_evidence,
        predicted_evidence_count=len(evidence_ranked),
        relation_path_correctness=relation_correctness,
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
    supported_findings = {
        finding.code
        for finding in prediction.findings
        if all(
            predicted_evidence_by_id[evidence_id] in expected_evidence
            for evidence_id in finding.evidence_ids
        )
    }
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
        evidence_recall=_recall(
            set(predicted_evidence), expected_evidence
        ),
        valid_evidence_count=sum(
            item in expected_evidence for item in predicted_evidence
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
        valid_evidence_rate=None,
        relation_path_correctness=0.0,
        changed_symbol_precision=0.0,
        changed_symbol_recall=0.0,
        direct_impact_recall=0.0,
        finding_precision=0.0,
        unsupported_claim_rate=None,
        abstention_correctness=None,
        total_duration_ms=0.0,
    )
    unmet_targets = _unmet_targets(metrics, "not_implemented")
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
            "Valid evidence rate",
            _format_metric(report.metrics.valid_evidence_rate),
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
    unmet_targets = _unmet_targets(metrics, predictions.implementation_status)
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
    exact = [
        float(score.exact_symbol_resolved)
        for score in query_scores
        if score.exact_symbol_resolved is not None
    ]
    symbol_scores = [
        score.symbols
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_symbols
    ]
    query_evidence_recall = [
        score.evidence.recall
        for score, case in zip(
            query_scores, dataset.query_cases, strict=True
        )
        if case.expected_evidence
    ]
    change_evidence_recall = [
        score.evidence_recall
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
        if case.expected_relations
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
    claim_count = sum(score.claim_count for score in query_scores) + sum(
        score.claim_count for score in change_scores
    )
    forbidden_count = sum(
        score.forbidden_claim_count for score in query_scores
    ) + sum(score.forbidden_claim_count for score in change_scores)
    return AggregateMetrics(
        exact_symbol_resolution=_mean(exact),
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
        valid_evidence_rate=(
            valid_evidence / predicted_evidence
            if predicted_evidence
            else None
        ),
        relation_path_correctness=_mean(relation_scores),
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
        unsupported_claim_rate=(
            forbidden_count / claim_count if claim_count else None
        ),
        abstention_correctness=_mean(
            [float(score.abstention_correct) for score in query_scores]
        ),
        total_duration_ms=sum(
            score.duration_ms for score in query_scores
        )
        + sum(score.duration_ms for score in change_scores),
    )


def _unmet_targets(
    metrics: AggregateMetrics,
    implementation_status: str,
) -> list[str]:
    minimums: dict[str, tuple[MetricValue, float]] = {
        "exact_symbol_resolution": (metrics.exact_symbol_resolution, 0.98),
        "primary_evidence_recall_at_10": (
            metrics.primary_evidence_recall_at_10,
            0.90,
        ),
        "changed_symbol_precision": (
            metrics.changed_symbol_precision,
            0.95,
        ),
        "changed_symbol_recall": (metrics.changed_symbol_recall, 0.95),
        "direct_impact_recall": (metrics.direct_impact_recall, 0.90),
    }
    unmet = [
        name
        for name, (value, target) in minimums.items()
        if value is None or value < target
    ]
    if implementation_status == "implemented" and (
        metrics.valid_evidence_rate is None
        or metrics.valid_evidence_rate < 1.0
    ):
        unmet.append("valid_evidence_rate")
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
