from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import load_dataset
from codeatlas.evaluation.runner import (
    ChangePrediction,
    EvidencePrediction,
    FindingPrediction,
    PredictionFile,
    QueryPrediction,
    contains_forbidden_claim,
    evaluate_predictions,
    null_baseline,
    ranked_metrics,
    render_markdown,
    score_change_case,
    score_query_case,
)

DATASET_ROOT = Path("tests/evaluation/cases")


def test_ranked_metrics_use_recall_mrr_and_ndcg_definitions() -> None:
    metrics = ranked_metrics(
        required=["alpha", "beta"],
        ranked=["noise", "beta", "alpha"],
        limit=3,
    )

    assert metrics.recall == 1.0
    assert metrics.reciprocal_rank == 0.5
    expected_ndcg = (
        1 / math.log2(3) + 1 / math.log2(4)
    ) / (1 + 1 / math.log2(3))
    assert metrics.ndcg == expected_ndcg


def test_ranked_metrics_ignore_duplicate_candidates() -> None:
    metrics = ranked_metrics(
        required=["alpha"],
        ranked=["alpha", "alpha"],
        limit=10,
    )

    assert metrics.recall == 1.0
    assert metrics.reciprocal_rank == 1.0
    assert metrics.ndcg == 1.0


def test_forbidden_claim_matching_normalizes_unicode_case_and_whitespace() -> None:
    assert contains_forbidden_claim(
        "THE  CAFÉ\nGUARANTEES exactly-once execution.",
        ["The cafe\u0301 guarantees exactly-once execution."],
    )
    assert not contains_forbidden_claim(
        "The café reports duplicate requests.",
        ["The café guarantees exactly-once execution."],
    )


def test_query_scoring_detects_invented_evidence_and_forbidden_claim() -> None:
    case = load_dataset(DATASET_ROOT).query_cases[0]
    prediction = QueryPrediction(
        case_id="q001",
        ranked_symbols=["PaymentService"],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id="python-v1",
                file_path="invented.py",
                start_line=1,
                end_line=1,
            )
        ],
        relation_paths=[],
        claims=["PaymentService commits a database transaction."],
        abstained=False,
        duration_ms=1.0,
    )

    score = score_query_case(case, prediction)

    assert score.exact_symbol_resolved is True
    assert score.evidence.recall == 0.0
    assert score.valid_evidence_count == 0
    assert score.predicted_evidence_count == 1
    assert score.forbidden_claim_count == 1
    assert score.abstention_correct is True


def test_change_scoring_calculates_symbol_precision_and_impact_recall() -> None:
    case = load_dataset(DATASET_ROOT).change_cases[0]
    prediction = ChangePrediction(
        case_id="c001",
        changed_symbols=["PaymentService.capture", "invented"],
        impact_paths=[
            ["PaymentService.capture", "test_capture_uses_idempotency_store"]
        ],
        findings=[
            FindingPrediction(
                code="PUBLIC_BEHAVIOR_CHANGED",
                evidence_ids=["predicted-1"],
            )
        ],
        evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id="python-v1",
                file_path="src/payments/service.py",
                start_line=7,
                end_line=11,
            )
        ],
        claims=[],
        duration_ms=2.0,
    )

    score = score_change_case(case, prediction)

    assert score.changed_symbol_precision == 0.5
    assert score.changed_symbol_recall == 1.0
    assert score.direct_impact_recall == 1.0
    assert score.finding_precision == 1.0
    assert score.valid_evidence_count == 1
    assert score.evidence_recall == 1.0


def test_change_prediction_rejects_finding_without_known_evidence() -> None:
    with pytest.raises(ValueError, match="unknown evidence"):
        ChangePrediction(
            case_id="c001",
            changed_symbols=["PaymentService.capture"],
            impact_paths=[],
            findings=[
                FindingPrediction(
                    code="PUBLIC_BEHAVIOR_CHANGED",
                    evidence_ids=["missing"],
                )
            ],
            evidence=[],
            claims=[],
            duration_ms=0.0,
        )


def test_stale_snapshot_prediction_is_not_valid_evidence() -> None:
    case = load_dataset(DATASET_ROOT).query_cases[0]
    prediction = QueryPrediction(
        case_id="q001",
        ranked_symbols=["PaymentService"],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id="stale-snapshot",
                file_path="src/payments/service.py",
                start_line=3,
                end_line=11,
            )
        ],
        relation_paths=[],
        claims=[],
        abstained=False,
        duration_ms=0.0,
    )

    score = score_query_case(case, prediction)

    assert score.valid_evidence_count == 0


def test_null_baseline_is_honest_and_deterministic() -> None:
    dataset = load_dataset(DATASET_ROOT)

    first = null_baseline(dataset)
    second = null_baseline(dataset)

    assert first == second
    assert first.implementation_status == "not_implemented"
    assert first.case_counts == {"queries": 40, "changes": 24}
    assert first.metrics.exact_symbol_resolution == 0.0
    assert first.metrics.symbol_recall_at_10 == 0.0
    assert first.metrics.mean_reciprocal_rank == 0.0
    assert first.metrics.relation_path_correctness == 0.0
    assert first.metrics.changed_symbol_recall == 0.0
    assert first.metrics.valid_evidence_rate is None
    assert first.metrics.unsupported_claim_rate is None
    assert first.metrics.abstention_correctness is None


def test_evaluation_rejects_duplicate_prediction_ids() -> None:
    prediction = QueryPrediction(
        case_id="q001",
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=True,
        duration_ms=0.0,
    )

    try:
        PredictionFile(query_predictions=[prediction, prediction])
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate prediction IDs were accepted")


def test_markdown_report_contains_status_counts_and_metrics() -> None:
    report = null_baseline(load_dataset(DATASET_ROOT))

    rendered = render_markdown(report)

    assert "# CodeAtlas Evaluation Report" in rendered
    assert "not_implemented" in rendered
    assert "| Query cases | 40 |" in rendered
    assert "| Exact symbol resolution | 0.0000 |" in rendered
    assert "not applicable" in rendered


def test_evaluate_predictions_marks_unmet_release_targets() -> None:
    dataset = load_dataset(DATASET_ROOT)
    predictions = PredictionFile()

    report = evaluate_predictions(dataset, predictions)

    assert report.targets_met is False
    assert "exact_symbol_resolution" in report.unmet_targets
    assert report.metrics.symbol_recall_at_10 == 0.0
    assert report.metrics.mean_reciprocal_rank == 0.0
    assert report.metrics.relation_path_correctness == 0.0


def test_prediction_file_round_trips_versioned_json() -> None:
    predictions = PredictionFile()

    payload = json.loads(predictions.model_dump_json())

    assert payload == {
        "contract_version": "1.0",
        "implementation_status": "implemented",
        "query_predictions": [],
        "change_predictions": [],
    }
