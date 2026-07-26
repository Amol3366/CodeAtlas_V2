"""The evaluation adapter must report the engine honestly."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import load_dataset
from codeatlas.evaluation.engine_adapter import (
    SUPPORTED_FIXTURES,
    SUPPORTED_INTENTS,
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
