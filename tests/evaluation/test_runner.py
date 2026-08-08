from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import (
    LEXICAL_INTENTS,
    SYMBOL_INTENTS,
    load_dataset,
)
from codeatlas.evaluation.runner import (
    ChangePrediction,
    EvaluationReport,
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


# --- ADR-0003: evidence granularity is measured, not chosen -------------------
#
# `q001` expects `src/payments/service.py` lines 3-11 in snapshot `python-v1`.
# Each case below varies the predicted range against that one expectation, so
# the two metrics can be told apart by construction rather than by aggregate
# drift.


def _q001_prediction(
    *,
    file_path: str = "src/payments/service.py",
    snapshot_id: str = "python-v1",
    start_line: int,
    end_line: int,
) -> QueryPrediction:
    return QueryPrediction(
        case_id="q001",
        ranked_symbols=["PaymentService"],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id=snapshot_id,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
            )
        ],
        relation_paths=[],
        claims=[],
        abstained=False,
        duration_ms=0.0,
    )


def test_a_containing_prediction_scores_on_containment_but_not_exactness() -> None:
    """The case that motivated ADR-0003: right file, wider range."""
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(case, _q001_prediction(start_line=1, end_line=20))

    assert score.valid_evidence_count == 0
    assert score.containing_evidence_count == 1


def test_an_exact_prediction_scores_on_both_metrics() -> None:
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(case, _q001_prediction(start_line=3, end_line=11))

    assert score.valid_evidence_count == 1
    assert score.containing_evidence_count == 1


def test_a_merely_overlapping_prediction_scores_on_neither_metric() -> None:
    """Overlap is not containment: half an answer has not proven the claim."""
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(case, _q001_prediction(start_line=5, end_line=20))

    assert score.valid_evidence_count == 0
    assert score.containing_evidence_count == 0


def test_containment_does_not_cross_files() -> None:
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(
        case, _q001_prediction(file_path="src/other.py", start_line=1, end_line=20)
    )

    assert score.containing_evidence_count == 0


def test_containment_does_not_cross_snapshots() -> None:
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(
        case, _q001_prediction(snapshot_id="stale-snapshot", start_line=1, end_line=20)
    )

    assert score.containing_evidence_count == 0


def test_aggregate_reports_exact_and_containing_rates_separately() -> None:
    dataset = load_dataset(DATASET_ROOT)
    predictions = PredictionFile(
        query_predictions=[_q001_prediction(start_line=1, end_line=20)]
    )

    report = evaluate_predictions(dataset, predictions)

    assert report.metrics.exact_evidence_rate == 0.0
    assert report.metrics.containing_evidence_rate == 1.0
    # Retained as the stricter of the two so no historical number changes
    # meaning.
    assert report.metrics.valid_evidence_rate == report.metrics.exact_evidence_rate


def test_containing_rate_is_never_below_the_exact_rate() -> None:
    dataset = load_dataset(DATASET_ROOT)
    predictions = PredictionFile(
        query_predictions=[
            _q001_prediction(start_line=3, end_line=11),
        ]
    )

    report = evaluate_predictions(dataset, predictions)
    exact = report.metrics.exact_evidence_rate
    containing = report.metrics.containing_evidence_rate
    assert exact is not None and containing is not None
    assert containing >= exact


def test_change_scoring_counts_containment_separately() -> None:
    dataset = load_dataset(DATASET_ROOT)
    case = dataset.change_cases[0]
    expected = case.expected_evidence[0]
    prediction = ChangePrediction(
        case_id=case.id,
        changed_symbols=[],
        impact_paths=[],
        findings=[],
        evidence=[
            EvidencePrediction(
                evidence_id="predicted-1",
                snapshot_id=expected.snapshot_id,
                file_path=expected.file_path,
                start_line=max(1, expected.start_line - 1),
                end_line=expected.end_line + 1,
            )
        ],
        claims=[],
        duration_ms=0.0,
    )

    score = score_change_case(case, prediction)

    assert score.valid_evidence_count == 0
    assert score.containing_evidence_count == 1


def test_both_evidence_rates_are_not_applicable_without_predictions() -> None:
    report = null_baseline(load_dataset(DATASET_ROOT))

    assert report.metrics.exact_evidence_rate is None
    assert report.metrics.containing_evidence_rate is None


def test_markdown_report_names_both_evidence_metrics() -> None:
    report = null_baseline(load_dataset(DATASET_ROOT))

    rendered = render_markdown(report)

    assert "Exact evidence rate" in rendered
    assert "Containing evidence rate" in rendered


def test_prediction_file_round_trips_versioned_json() -> None:
    predictions = PredictionFile()

    payload = json.loads(predictions.model_dump_json())

    assert payload == {
        "contract_version": "1.0",
        "implementation_status": "implemented",
        "query_predictions": [],
        "change_predictions": [],
    }


# --- Target profiles and metric scope (ADR-0023) --------------------------------


def _report(dataset_root: Path) -> EvaluationReport:
    dataset = load_dataset(dataset_root)
    predictions = PredictionFile(
        implementation_status="implemented",
        query_predictions=[],
        change_predictions=[],
    )
    return evaluate_predictions(dataset, predictions)


def test_exact_symbol_resolution_covers_only_symbol_shaped_intents() -> None:
    """The metric's name and its 0.98 target describe symbol resolution.

    Scoring "which config key matches this text" as a top-1 *symbol* result
    blends two different questions into one number, so a regression in exact
    lookup can hide behind a gain in document lookup.
    """
    dataset = load_dataset(DATASET_ROOT)
    scored = [
        case
        for case in dataset.query_cases
        if case.intent in SYMBOL_INTENTS and case.expected_symbols
    ]
    lexical = [
        case
        for case in dataset.query_cases
        if case.intent in LEXICAL_INTENTS and case.expected_symbols
    ]

    assert scored, "the corpus must contain symbol-shaped cases"
    assert lexical, "the corpus must contain lexical cases"
    assert not (SYMBOL_INTENTS & LEXICAL_INTENTS), "an intent belongs to one group"


def test_lexical_resolution_is_reported_and_gated() -> None:
    """Scoping the symbol metric must not leave lexical intents unmeasured."""
    report = _report(DATASET_ROOT)

    assert report.metrics.lexical_resolution is not None
    assert "lexical_resolution" in report.unmet_targets


def test_the_conceptual_profile_drops_targets_it_cannot_measure() -> None:
    """A corpus of fuzzy questions is not held to top-1 or exact-span rules."""
    report = _report(Path("tests/evaluation/semantic_cases"))

    assert "exact_symbol_resolution" not in report.unmet_targets
    assert "lexical_resolution" not in report.unmet_targets
    assert "symbol_recall_at_10" in report.unmet_targets


def test_the_evidence_gate_reads_containing_rather_than_exact_spans() -> None:
    """ADR-0003: a call site rarely equals a gold range describing a definition.

    The threshold stays 1.0 — "all evidence must be valid" is unchanged. Only
    what *valid* means is corrected, so nothing was quietly relaxed.
    """
    report = _report(DATASET_ROOT)

    assert "containing_evidence_rate" in report.unmet_targets
    assert "valid_evidence_rate" not in report.unmet_targets
    # Still reported, because the gap between the two rates is the measurement.
    # (Both are None here: an empty prediction file predicts no evidence at all.
    # What matters is that the report still carries the field.)
    assert "exact_evidence_rate" in report.metrics.model_dump()


# --- Unmeasured cases are not wrong answers (ADR-0024) --------------------------


def _prediction(case_id: str, *, measured: bool) -> QueryPrediction:
    return QueryPrediction(
        case_id=case_id,
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=True,
        duration_ms=0.0,
        measured=measured,
    )


def test_a_case_the_adapter_never_ran_is_not_scored_as_a_miss() -> None:
    """"Not implemented" and "answered wrongly" are different facts.

    `engine_adapter`'s own docstring says the baseline must not blur them, and
    the scoring blurred exactly those two: a case the adapter deliberately
    refused to run produced an abstention that landed in the denominator as a
    wrong answer, indistinguishable from the engine getting it wrong.
    """
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(case, _prediction(case.id, measured=False))

    assert score.exact_symbol_resolved is None


def test_an_engine_abstention_is_still_a_miss() -> None:
    """The distinction only helps if the other side of it still bites.

    A case the engine *did* run and could not answer is a real miss. Excluding
    it would let the metric improve by refusing to answer.
    """
    case = load_dataset(DATASET_ROOT).query_cases[0]

    score = score_query_case(case, _prediction(case.id, measured=True))

    assert score.exact_symbol_resolved is False


def test_unmeasured_cases_leave_the_lexical_denominator() -> None:
    """The two `malicious_unsupported` cases can never pass, by design.

    `SUPPORTED_FIXTURES` excludes that fixture on purpose (ADR-0017), so
    counting its cases as wrong answers put a ceiling of 0.80 on a metric
    gated at 0.90 — a target no engine could clear.
    """
    dataset = load_dataset(DATASET_ROOT)
    predictions = PredictionFile(
        implementation_status="implemented",
        query_predictions=[
            _prediction(
                case.id,
                measured=case.repository_fixture != "malicious_unsupported",
            )
            for case in dataset.query_cases
        ],
        change_predictions=[],
    )

    report = evaluate_predictions(dataset, predictions)

    # Every measured case abstained, so the rate is 0.0 rather than None; the
    # point is that it is computed over the measured cases only.
    assert report.metrics.lexical_resolution == 0.0
    assert report.metrics.abstention_correctness is not None
