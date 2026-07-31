"""Measure the semantic layer against the deterministic baseline.

Gate condition 7 asks for uplift *over the deterministic baseline*, so this
runs the same corpus twice through the same pipeline and reports both sides
next to each other. One switch differs between the runs — whether a fusion
layer is attached — because any second difference would make the delta a
property of this script rather than of semantic retrieval.

Both runs need the `semantic-local` extra installed: the deterministic side
does not use it, but running the two sides in different environments would
compare two things that differ in more than the switch.

Usage::

    uv run python scripts/run_phase7_baseline.py \\
        --dataset tests/evaluation/semantic_cases \\
        --json-output docs/evaluation/baseline-phase-7.json \\
        --markdown-output docs/evaluation/baseline-phase-7.md [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codeatlas.evaluation.cli import (
    EXIT_INTERNAL_FAILURE,
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
)
from codeatlas.evaluation.dataset import Dataset, DatasetError, load_dataset
from codeatlas.evaluation.engine_adapter import predict_changes, predict_conceptual
from codeatlas.evaluation.runner import (
    EvaluationError,
    EvaluationReport,
    PredictionFile,
    evaluate_predictions,
)

# The metrics the admission decision turns on. Reported in this order in the
# Markdown so the recall gain and the precision cost are read together; quoting
# either alone misrepresents the result.
_COMPARED = (
    ("primary_evidence_recall_at_10", "Primary evidence Recall@10", True),
    ("exact_evidence_rate", "Exact evidence rate", True),
    ("containing_evidence_rate", "Containing evidence rate", True),
    ("exact_symbol_resolution", "Exact symbol resolution", True),
    ("abstention_correctness", "Abstention correctness", True),
    ("unsupported_claim_rate", "Unsupported claim rate", False),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure semantic uplift over the deterministic baseline."
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

        deterministic = _run(dataset, semantic=False)
        semantic = _run(dataset, semantic=True)

        payload = _payload(dataset, deterministic, semantic)
        json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        markdown_text = _render(payload)

        if args.check:
            if not (
                _matches(args.json_output, json_text)
                and _matches(args.markdown_output, markdown_text)
            ):
                print(
                    "Phase 7 baseline artifacts are stale. Regenerate them"
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


def _run(dataset: Dataset, *, semantic: bool) -> EvaluationReport:
    """One side of the comparison, with timings excluded.

    Wall times differ on every machine, so including them would make a tracked
    artifact impossible to verify byte-for-byte. Latency is a Phase 7
    performance question (P7-12), measured separately with its hardware named.
    """
    queries = predict_conceptual(dataset, semantic=semantic, record_timings=False)
    changes = predict_changes(dataset, record_timings=False)
    return evaluate_predictions(
        dataset,
        PredictionFile(
            implementation_status="implemented",
            query_predictions=queries.query_predictions,
            change_predictions=changes.change_predictions,
        ),
    )


def _payload(
    dataset: Dataset,
    deterministic: EvaluationReport,
    semantic: EvaluationReport,
) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    for name, _label, _higher_is_better in _COMPARED:
        before = getattr(deterministic.metrics, name)
        after = getattr(semantic.metrics, name)
        comparison[name] = {
            "deterministic": before,
            "semantic": after,
            "delta": None if before is None or after is None else after - before,
        }
    return {
        "contract_version": "1.0",
        "corpus": {
            "query_cases": len(dataset.query_cases),
            "change_cases": len(dataset.change_cases),
        },
        "deterministic": deterministic.model_dump(mode="json"),
        "semantic": semantic.model_dump(mode="json"),
        "comparison": comparison,
    }


def _render(payload: dict[str, Any]) -> str:
    rows = []
    for name, label, _higher in _COMPARED:
        entry = payload["comparison"][name]
        rows.append(
            f"| {label} | {_metric(entry['deterministic'])} |"
            f" {_metric(entry['semantic'])} | {_delta(entry['delta'])} |"
        )
    body = "\n".join(rows)
    corpus = payload["corpus"]
    return (
        "# CodeAtlas Phase 7 Semantic Uplift Baseline\n\n"
        f"- Contract version: `{payload['contract_version']}`\n"
        f"- Query cases: {corpus['query_cases']}\n"
        f"- Change cases: {corpus['change_cases']}\n\n"
        "Both columns are the same corpus through the same pipeline. The only\n"
        "difference is whether a semantic fusion layer is attached.\n\n"
        "| Metric | Deterministic | Semantic | Delta |\n"
        "| --- | ---: | ---: | ---: |\n"
        f"{body}\n"
    )


def _metric(value: float | None) -> str:
    return "not applicable" if value is None else f"{value:.4f}"


def _delta(value: float | None) -> str:
    if value is None:
        return "not applicable"
    return f"{value:+.4f}"


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
