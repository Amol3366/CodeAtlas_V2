"""Command-line adapter for deterministic CodeAtlas evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from codeatlas.evaluation.dataset import DatasetError, load_dataset
from codeatlas.evaluation.runner import (
    EvaluationError,
    EvaluationReport,
    PredictionFile,
    evaluate_predictions,
    null_baseline,
    render_markdown,
)

EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 2
EXIT_TARGETS_UNMET = 3
EXIT_INTERNAL_FAILURE = 4
EXIT_STALE_ARTIFACT = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and evaluate CodeAtlas benchmark cases."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    _add_dataset_argument(validate)

    baseline = subparsers.add_parser("null-baseline")
    _add_dataset_argument(baseline)
    _add_output_arguments(baseline)
    baseline.add_argument("--check", action="store_true")

    evaluate = subparsers.add_parser("evaluate")
    _add_dataset_argument(evaluate)
    evaluate.add_argument(
        "--predictions", type=Path, required=True
    )
    evaluate.add_argument("--enforce-targets", action="store_true")
    _add_output_arguments(evaluate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        dataset = load_dataset(args.dataset)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "contract_version": dataset.contract_version,
                        "fixtures": len(dataset.fixtures),
                        "query_cases": len(dataset.query_cases),
                        "change_cases": len(dataset.change_cases),
                        "status": "valid",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return EXIT_SUCCESS

        if args.command == "null-baseline":
            report = null_baseline(dataset)
            if args.check:
                if args.json_output is None or args.markdown_output is None:
                    raise EvaluationError(
                        "--check requires both output paths"
                    )
                return (
                    EXIT_SUCCESS
                    if _report_matches(
                        report, args.json_output, args.markdown_output
                    )
                    else EXIT_STALE_ARTIFACT
                )
            _emit_report(report, args.json_output, args.markdown_output)
            return EXIT_SUCCESS

        predictions = PredictionFile.model_validate(
            _read_json(args.predictions)
        )
        report = evaluate_predictions(dataset, predictions)
        _emit_report(report, args.json_output, args.markdown_output)
        if args.enforce_targets and not report.targets_met:
            return EXIT_TARGETS_UNMET
        return EXIT_SUCCESS
    except (
        DatasetError,
        EvaluationError,
        OSError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Internal evaluation failure: {exc}", file=sys.stderr)
        return EXIT_INTERNAL_FAILURE


def _add_dataset_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", type=Path, required=True)


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)


def _emit_report(
    report: EvaluationReport,
    json_output: Path | None,
    markdown_output: Path | None,
) -> None:
    json_text = _report_json(report)
    if json_output is None:
        print(json_text, end="")
    else:
        _write_text(json_output, json_text)
    if markdown_output is not None:
        _write_text(markdown_output, render_markdown(report))


def _report_json(report: EvaluationReport) -> str:
    return json.dumps(
        report.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    ) + "\n"


def _report_matches(
    report: EvaluationReport,
    json_output: Path,
    markdown_output: Path,
) -> bool:
    try:
        return (
            json_output.read_text(encoding="utf-8") == _report_json(report)
            and markdown_output.read_text(encoding="utf-8")
            == render_markdown(report)
        )
    except FileNotFoundError:
        return False


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
