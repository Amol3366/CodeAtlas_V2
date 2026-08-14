"""P4-10: the change-evaluation adapter over the declared corpus.

Two layers are pinned here, and the split matters:

1. **State resolution** (`dataset.py`). Decision 12's ref grammar is pairwise:
   a `working-tree:<slug>` target owns *both* sides of its case — the base side
   consults the same slug's ``base/`` overlay before defaulting to the fixture
   root. The `git_changes` fixture keeps both of its sides as subdirectories of
   one root, so its refs *select* a side rather than merging the root, and the
   corpus labels its file paths with the side-directory prefix.
2. **Prediction mapping** (`engine_adapter.predict_changes`). Every declared
   case runs through the real `ChangeAnalysisEngine` over two materialized
   directories, and the engine's names are mapped onto the corpus labels
   (file-stem document prefixes in `docs_config`, dotted configuration paths,
   side-directory path prefixes) without inventing anything the engine did not
   report.

The corpus itself is never edited to make these pass (ADR-0003).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import ChangeCase, Dataset, load_dataset
from codeatlas.evaluation.engine_adapter import predict_changes
from codeatlas.evaluation.runner import (
    ChangePrediction,
    ChangeScore,
    score_change_case,
)

CASES_ROOT = Path(__file__).resolve().parent / "cases"


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return load_dataset(CASES_ROOT)


@pytest.fixture(scope="module")
def cases(dataset: Dataset) -> dict[str, ChangeCase]:
    return {case.id: case for case in dataset.change_cases}


@pytest.fixture(scope="module")
def predictions(dataset: Dataset) -> dict[str, ChangePrediction]:
    prediction_file = predict_changes(dataset, record_timings=False)
    return {
        item.case_id: item for item in prediction_file.change_predictions
    }


@pytest.fixture(scope="module")
def scores(
    dataset: Dataset, predictions: dict[str, ChangePrediction]
) -> dict[str, ChangeScore]:
    return {
        case.id: score_change_case(case, predictions[case.id])
        for case in dataset.change_cases
    }


def _variants(dataset: Dataset) -> Path:
    return dataset.fixtures_root.parent / "variants"


# --- State resolution: decision 12's grammar, pairwise -----------------------


def test_a_working_tree_target_resolves_its_base_against_the_same_slug(
    dataset: Dataset, cases: dict[str, ChangeCase]
) -> None:
    """c001's base is the slug's `base/` overlay, not the bare fixture root.

    This is the defect the previous handoff recorded: `base_ref` of `HEAD`
    resolved independently, both sides landed on the fixture root, and every
    `base/`-overlay case scored zero because the engine was handed two
    identical states.
    """
    case = cases["c001"]
    assert case.base_state.root == dataset.fixtures_root / "python_app"
    assert case.base_state.overlay == (
        _variants(dataset) / "python_app" / "key-validation" / "base"
    )
    assert case.base_state.label_prefix == ""
    assert case.target_state.root == dataset.fixtures_root / "python_app"
    assert case.target_state.overlay is None


def test_a_target_overlay_case_keeps_its_bare_base(
    dataset: Dataset, cases: dict[str, ChangeCase]
) -> None:
    case = cases["c006"]
    assert case.base_state.overlay is None
    assert case.target_state.overlay == (
        _variants(dataset) / "python_app" / "delete-fake" / "target"
    )


def test_bare_side_refs_select_the_side_directory(
    dataset: Dataset, cases: dict[str, ChangeCase]
) -> None:
    """`git_changes` sides are selected, never merged into one tree."""
    case = cases["c020"]
    fixture = dataset.fixtures_root / "git_changes"
    assert case.base_state.root == fixture / "base"
    assert case.base_state.overlay is None
    assert case.base_state.label_prefix == "base/"
    assert case.target_state.root == fixture / "target"
    assert case.target_state.overlay is None
    assert case.target_state.label_prefix == "target/"


def test_a_named_variant_overlays_the_named_side_directory(
    dataset: Dataset, cases: dict[str, ChangeCase]
) -> None:
    """`target:strict` starts from `target/` and applies the strict overlay."""
    case = cases["c022"]
    fixture = dataset.fixtures_root / "git_changes"
    assert case.target_state.root == fixture / "target"
    assert case.target_state.overlay == (
        _variants(dataset) / "git_changes" / "target-strict" / "target"
    )
    assert case.target_state.label_prefix == "target/"


def test_a_working_tree_target_starts_from_its_bases_selected_side(
    dataset: Dataset, cases: dict[str, ChangeCase]
) -> None:
    """c023 edits the *target* side in place: base `target`, working tree on top."""
    case = cases["c023"]
    fixture = dataset.fixtures_root / "git_changes"
    assert case.base_state.root == fixture / "target"
    assert case.base_state.label_prefix == "target/"
    assert case.target_state.root == fixture / "target"
    assert case.target_state.overlay == (
        _variants(dataset) / "git_changes" / "error-message" / "target"
    )
    assert case.target_state.label_prefix == "target/"


# --- Predictions: every case, honestly ---------------------------------------


def test_every_declared_case_is_predicted(
    cases: dict[str, ChangeCase], predictions: dict[str, ChangePrediction]
) -> None:
    assert set(predictions) == set(cases)


def test_no_case_is_answered_with_an_empty_prediction(
    predictions: dict[str, ChangePrediction],
) -> None:
    """Every declared case has a real change; an empty prediction means the
    adapter handed the engine two identical states.

    c028 is the one declared exception and is exempt by id, not by widening the
    rule: its two states differ in bytes and agree in content, so "no changed
    symbols" *is* its expectation (ADR-0043). Note what this costs — for c028
    alone, a genuine adapter failure produces the same empty prediction as a
    pass, because `_empty_change` emits exactly this shape when the engine
    raises. `test_the_crlf_case_still_holds_the_bytes_it_measures` is what keeps
    that from being silent: it asserts the two sides really do differ on disk.
    """
    empty = sorted(
        case_id
        for case_id, item in predictions.items()
        if not item.changed_symbols and case_id != "c028"
    )
    assert empty == []


def test_every_declared_changed_symbol_is_found(
    scores: dict[str, ChangeScore],
) -> None:
    missing = {
        case_id: score.changed_symbol_recall
        for case_id, score in scores.items()
        if score.changed_symbol_recall < 1.0
    }
    assert missing == {}


def test_overlay_cases_predict_exactly_the_declared_symbols(
    scores: dict[str, ChangeScore],
) -> None:
    """Precision is 1.0 wherever the corpus declares the whole comparison.

    The three `git_changes` comparisons that share one state pair (c020/c021)
    or inherit the fixture's deleted `legacy` (c022) each declare only their
    own subject, so the honest full diff caps their precision at 0.5. They are
    pinned separately; everything else must be exact.
    """
    shared_comparison = {"c020", "c021", "c022"}
    imprecise = {
        case_id: score.changed_symbol_precision
        for case_id, score in scores.items()
        if case_id not in shared_comparison
        and score.changed_symbol_precision < 1.0
    }
    assert imprecise == {}


def test_shared_comparison_cases_report_the_full_honest_diff(
    scores: dict[str, ChangeScore],
) -> None:
    """c020/c021 split one comparison; c022 inherits `legacy`'s deletion.

    Each prediction carries both truly-changed symbols while the case declares
    one, so precision is exactly 0.5 — not lower (nothing invented) and not
    higher (nothing suppressed to meet a number).
    """
    for case_id in ("c020", "c021", "c022"):
        assert scores[case_id].changed_symbol_precision == 0.5
        assert scores[case_id].changed_symbol_recall == 1.0


def test_every_declared_impact_path_is_reproduced(
    scores: dict[str, ChangeScore],
) -> None:
    missing = {
        case_id: score.direct_impact_recall
        for case_id, score in scores.items()
        if score.direct_impact_recall is not None
        and score.direct_impact_recall < 1.0
    }
    assert missing == {}


def test_git_changes_evidence_carries_side_prefixed_paths(
    predictions: dict[str, ChangePrediction],
) -> None:
    """The corpus labels `git_changes` files by side directory; predictions
    must speak the same language or every citation misses."""
    paths = {item.file_path for item in predictions["c020"].evidence}
    assert paths <= {"base/service.py", "target/processor.py"}
    assert "target/processor.py" in paths


def test_document_labels_follow_the_corpus_conventions(
    predictions: dict[str, ChangePrediction],
) -> None:
    """`docs_config` sections are stem-prefixed; `mixed_app` sections are not."""
    assert "README.Health" in predictions["c013"].changed_symbols
    assert "Order flow" in {
        name
        for path in predictions["c019"].impact_paths
        for name in path
    } | set(predictions["c019"].changed_symbols)


def test_configuration_keys_are_labeled_by_dotted_path(
    predictions: dict[str, ChangePrediction],
) -> None:
    assert "service.port" in predictions["c012"].changed_symbols


def test_deleted_symbols_are_reported_from_the_base_side(
    predictions: dict[str, ChangePrediction],
) -> None:
    prediction = predictions["c006"]
    assert "FakeStore" in prediction.changed_symbols
    base_side = [
        item
        for item in prediction.evidence
        if item.snapshot_id.endswith("-base")
    ]
    assert base_side, "a deletion can only be cited where the symbol existed"
