from __future__ import annotations

import json
from pathlib import Path

from codeatlas.evaluation.cli import (
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
    EXIT_TARGETS_UNMET,
    main,
)

DATASET_ROOT = Path("tests/evaluation/cases")


def test_validate_command_reports_dataset_counts(capsys: object) -> None:
    exit_code = main(["validate", "--dataset", str(DATASET_ROOT)])

    assert exit_code == EXIT_SUCCESS
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '"query_cases": 40' in output
    assert '"change_cases": 25' in output


def test_null_baseline_writes_stable_json_and_markdown(tmp_path: Path) -> None:
    json_output = tmp_path / "baseline.json"
    markdown_output = tmp_path / "baseline.md"

    exit_code = main(
        [
            "null-baseline",
            "--dataset",
            str(DATASET_ROOT),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == EXIT_SUCCESS
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["implementation_status"] == "not_implemented"
    assert payload["case_counts"] == {"changes": 25, "queries": 40}
    assert "# CodeAtlas Evaluation Report" in markdown_output.read_text(
        encoding="utf-8"
    )

    assert (
        main(
            [
                "null-baseline",
                "--dataset",
                str(DATASET_ROOT),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
                "--check",
            ]
        )
        == EXIT_SUCCESS
    )
    json_output.write_text("{}\n", encoding="utf-8")
    assert (
        main(
            [
                "null-baseline",
                "--dataset",
                str(DATASET_ROOT),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
                "--check",
            ]
        )
        == EXIT_STALE_ARTIFACT
    )


def test_evaluate_returns_invalid_input_for_malformed_predictions(
    tmp_path: Path,
    capsys: object,
) -> None:
    predictions = tmp_path / "predictions.json"
    predictions.write_text("{", encoding="utf-8")

    exit_code = main(
        [
            "evaluate",
            "--dataset",
            str(DATASET_ROOT),
            "--predictions",
            str(predictions),
        ]
    )

    assert exit_code == EXIT_INVALID_INPUT
    error = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "invalid input" in error.casefold()


def test_enforced_targets_return_distinct_exit_code(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.json"
    predictions.write_text(
        json.dumps(
            {
                "contract_version": "1.0",
                "implementation_status": "implemented",
                "query_predictions": [],
                "change_predictions": [],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "evaluate",
            "--dataset",
            str(DATASET_ROOT),
            "--predictions",
            str(predictions),
            "--enforce-targets",
        ]
    )

    assert exit_code == EXIT_TARGETS_UNMET
