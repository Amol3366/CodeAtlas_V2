"""Generate the honest Phase 4 evaluation baseline.

Phase 4 adds change assurance: the 24 declared change cases now run through the
real ``ChangeAnalysisEngine`` via ``predict_changes``, so the changed-symbol,
direct-impact, and finding metrics report what the engine actually does rather
than the zeros earlier phases recorded for unimplemented behavior. The query
intents are re-run unchanged through ``predict_exact_symbols`` so this artifact
carries every metric side by side — a Phase 4 claim about a query metric and a
change metric must come from the same corpus run.

Per ADR-0003 the report carries three evidence metrics side by side:
`valid_evidence_rate` (unchanged, and the stricter reading), `exact_evidence_rate`,
and `containing_evidence_rate`. Any claim made from this baseline must name which
one it used.

Usage::

    uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases \\
        --json-output docs/evaluation/baseline-phase-4.json \\
        --markdown-output docs/evaluation/baseline-phase-4.md [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from codeatlas.evaluation.cli import (
    EXIT_INTERNAL_FAILURE,
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
)
from codeatlas.evaluation.dataset import DatasetError, load_dataset
from codeatlas.evaluation.engine_adapter import (
    predict_changes,
    predict_exact_symbols,
)
from codeatlas.evaluation.runner import (
    EvaluationError,
    EvaluationReport,
    PredictionFile,
    evaluate_predictions,
    render_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Phase 4 engine over the evaluation corpus."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against the tracked artifacts instead of overwriting them.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        dataset = load_dataset(args.dataset)
        # Timings are excluded so the tracked artifact is byte-for-byte
        # reproducible on any machine; see the environment document.
        queries = predict_exact_symbols(dataset, record_timings=False)
        changes = predict_changes(dataset, record_timings=False)
        predictions = PredictionFile(
            implementation_status="implemented",
            query_predictions=queries.query_predictions,
            change_predictions=changes.change_predictions,
        )
        report = evaluate_predictions(dataset, predictions)

        json_text = _report_json(report)
        markdown_text = render_markdown(report)

        if args.check:
            matches = _matches(
                args.json_output, json_text
            ) and _matches(args.markdown_output, markdown_text)
            if not matches:
                print(
                    "Phase 4 baseline artifacts are stale. Regenerate them"
                    " without --check and review the diff.",
                    file=sys.stderr,
                )
                return EXIT_STALE_ARTIFACT
            return EXIT_SUCCESS

        _write(args.json_output, json_text)
        _write(args.markdown_output, markdown_text)
        return EXIT_SUCCESS
    except (DatasetError, EvaluationError, OSError, json.JSONDecodeError) as error:
        print(f"Invalid input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        print(f"Internal baseline failure: {error}", file=sys.stderr)
        return EXIT_INTERNAL_FAILURE


def _report_json(report: EvaluationReport) -> str:
    return (
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _matches(path: Path, expected: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n") == expected
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
