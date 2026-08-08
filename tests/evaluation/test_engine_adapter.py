"""The evaluation adapter must report the engine honestly."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import load_dataset
from codeatlas.evaluation.engine_adapter import (
    SUPPORTED_FIXTURES,
    SUPPORTED_INTENTS,
    _query_term,
    predict_exact_symbols,
)
from codeatlas.evaluation.runner import PredictionFile

DATASET_ROOT = Path("tests/evaluation/cases")


@pytest.fixture(scope="module")
def predictions() -> PredictionFile:
    return predict_exact_symbols(load_dataset(DATASET_ROOT))


def test_every_case_receives_a_prediction(predictions: PredictionFile) -> None:
    dataset = load_dataset(DATASET_ROOT)
    predicted = {item.case_id for item in predictions.query_predictions}
    assert predicted == {case.id for case in dataset.query_cases}


def test_supported_python_cases_resolve_their_expected_symbol(
    predictions: PredictionFile,
) -> None:
    dataset = load_dataset(DATASET_ROOT)
    by_id = {item.case_id: item for item in predictions.query_predictions}

    resolved = 0
    supported = [
        case
        for case in dataset.query_cases
        if case.intent == "EXACT_SYMBOL" and case.repository_fixture == "python_app"
    ]
    assert supported, "the corpus must contain supported cases"

    for case in supported:
        prediction = by_id[case.id]
        if case.expected_symbols and case.expected_symbols[0] in (
            prediction.ranked_symbols
        ):
            resolved += 1

    assert resolved == len(supported)


def test_unsupported_intents_abstain_rather_than_guess(
    predictions: PredictionFile,
) -> None:
    dataset = load_dataset(DATASET_ROOT)
    by_id = {item.case_id: item for item in predictions.query_predictions}

    for case in dataset.query_cases:
        if (
            case.intent in SUPPORTED_INTENTS
            and case.repository_fixture in SUPPORTED_FIXTURES
        ):
            continue
        prediction = by_id[case.id]
        assert prediction.abstained is True
        assert prediction.ranked_symbols == []
        assert prediction.ranked_evidence == []


def test_every_corpus_fixture_is_measured_unless_deliberately_unsupported() -> None:
    """A new fixture must force a decision instead of silently scoring zero.

    `SUPPORTED_FIXTURES` gates whole cases out of the measurement, and a gated
    case scores `False` rather than `None` — it lands in the denominator as a
    miss. The tuple was written in Phase 1 and stayed put while the engine
    gained TypeScript (Phase 3) and Git (Phase 4), so four years of capability
    were being reported as failure. Deriving this expectation from the corpus
    rather than from the constant is the whole point: the neighbouring
    abstention test reads `SUPPORTED_FIXTURES` to build its own expectation and
    therefore passed throughout.
    """
    dataset = load_dataset(DATASET_ROOT)
    corpus_fixtures = {case.repository_fixture for case in dataset.query_cases}

    # `malicious_unsupported` carries prompt-injection text and is excluded on
    # purpose: measuring it would assert what the engine *should* return for
    # hostile input, which is a security question, not an accuracy one.
    assert corpus_fixtures - {"malicious_unsupported"} == set(SUPPORTED_FIXTURES)


@pytest.mark.parametrize(
    ("case_id", "fixture", "expected_symbol"),
    [
        ("q011", "tsjs_app", "Order"),
        ("q014", "tsjs_app", "render"),
        ("q033", "git_changes", "process"),
        ("q036", "git_changes", "legacy"),
    ],
)
def test_capabilities_shipped_after_phase_1_are_measured(
    predictions: PredictionFile,
    case_id: str,
    fixture: str,
    expected_symbol: str,
) -> None:
    """TypeScript shipped in Phase 3 and Git in Phase 4; both must be scored."""
    dataset = load_dataset(DATASET_ROOT)
    case = next(item for item in dataset.query_cases if item.id == case_id)
    assert case.repository_fixture == fixture, "corpus case moved fixture"

    by_id = {item.case_id: item for item in predictions.query_predictions}
    prediction = by_id[case_id]

    assert prediction.abstained is False
    assert prediction.ranked_symbols[:1] == [expected_symbol]


@pytest.mark.parametrize(
    ("case_id", "subject", "expected_top_symbol"),
    [
        ("q005", "IdempotencyStore.claim", "PaymentService.capture"),
        ("q016", "total", "render"),
    ],
)
def test_a_graph_case_is_asked_about_its_declared_subject(
    predictions: PredictionFile,
    case_id: str,
    subject: str,
    expected_top_symbol: str,
) -> None:
    """A graph query's subject is what is asked about, not what is expected back.

    `expected_symbols` lists the *answer*. For "Who calls total?" the answer is
    `render` and the subject is `total`, so using `expected_symbols[0]` as the
    lookup term asked the engine who calls `render` — a different question, whose
    correct answer scores as a miss.
    """
    dataset = load_dataset(DATASET_ROOT)
    case = next(item for item in dataset.query_cases if item.id == case_id)
    assert case.query_subject == subject
    assert case.expected_symbols[0] != subject, "case would pass without the field"

    prediction = {p.case_id: p for p in predictions.query_predictions}[case_id]
    assert prediction.ranked_symbols[:1] == [expected_top_symbol]


def test_a_case_without_a_declared_subject_falls_back_to_its_expected_symbol() -> None:
    dataset = load_dataset(DATASET_ROOT)
    case = next(item for item in dataset.query_cases if item.id == "q013")

    assert case.query_subject is None
    assert _query_term(case) == case.expected_symbols[0]


def test_an_outbound_relation_answer_is_read_from_the_step_not_the_label(
    predictions: PredictionFile,
) -> None:
    """q010 asks what `service` imports; the answer is not `service`.

    Evidence for an outbound relation cites the import statement, which lives in
    the importing module, so the evidence label names the subject. Reading the
    step's target is what distinguishes the answer from the question.
    """
    prediction = {p.case_id: p for p in predictions.query_predictions}["q010"]

    assert prediction.ranked_symbols[:1] == ["IdempotencyStore"]
    assert "src.payments.service" not in prediction.ranked_symbols


def test_a_trace_answer_still_includes_its_origin(
    predictions: PredictionFile,
) -> None:
    """The deliberate exception: a flow answer names where the flow starts."""
    prediction = {p.case_id: p for p in predictions.query_predictions}["q003"]

    assert prediction.ranked_symbols[:1] == ["PaymentService.capture"]


def test_relation_predictions_use_the_corpus_source_kind_target_form(
    predictions: PredictionFile,
) -> None:
    """Joining targets only produced strings no declared relation could equal."""
    prediction = {p.case_id: p for p in predictions.query_predictions}["q016"]

    assert "render CALLS total" in prediction.relation_paths


def test_no_evidence_references_a_file_the_engine_did_not_index(
    predictions: PredictionFile,
) -> None:
    dataset = load_dataset(DATASET_ROOT)
    fixture_by_case = {
        case.id: case.repository_fixture for case in dataset.query_cases
    }
    for prediction in predictions.query_predictions:
        fixture_root = dataset.fixtures_root / fixture_by_case[prediction.case_id]
        for evidence in prediction.ranked_evidence:
            assert (fixture_root / evidence.file_path).is_file()


def test_predictions_declare_the_implementation_status(
    predictions: PredictionFile,
) -> None:
    assert predictions.implementation_status == "implemented"
    assert predictions.change_predictions == []
