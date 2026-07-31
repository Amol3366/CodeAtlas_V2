"""Record the P7-10 reranking admission decision.

P7-10 has exactly one implemented reranker: `NoReranker`, whose contract is to
preserve candidate order and perform no provider call. The A/B therefore
compares the tracked semantic baseline to that identity reranker and records the
feature as declined because it provides no measured uplift.

This script is intentionally separate from `run_phase7_baseline.py`. A future
real reranker provider can replace the `reranked` side here without rewriting
the semantic baseline artifact P7-06 already admitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codeatlas.evaluation.cli import (
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
)
from codeatlas.semantic.reranking import NoReranker

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
        description="Record the Phase 7 rerank A/B admission decision."
    )
    parser.add_argument("--semantic-baseline", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against tracked artifacts instead of overwriting them.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        baseline = json.loads(args.semantic_baseline.read_text(encoding="utf-8"))
        payload = _payload(baseline)
        json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        markdown_text = _render(payload)

        if args.check:
            if not (
                _matches(args.json_output, json_text)
                and _matches(args.markdown_output, markdown_text)
            ):
                print(
                    "Phase 7 rerank artifacts are stale. Regenerate them"
                    " without --check and review the diff.",
                    file=sys.stderr,
                )
                return EXIT_STALE_ARTIFACT
            return EXIT_SUCCESS

        _write(args.json_output, json_text)
        _write(args.markdown_output, markdown_text)
        return EXIT_SUCCESS
    except (KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Invalid input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT


def _payload(baseline: dict[str, Any]) -> dict[str, Any]:
    semantic = baseline["semantic"]
    model = NoReranker()
    comparison: dict[str, Any] = {}
    admitted = False
    for name, _label, higher_is_better in _COMPARED:
        before = semantic["metrics"][name]
        after = semantic["metrics"][name]
        delta = None if before is None or after is None else after - before
        comparison[name] = {
            "semantic": before,
            "reranked": after,
            "delta": delta,
        }
        if delta is not None:
            admitted = admitted or (delta > 0 if higher_is_better else delta < 0)

    return {
        "contract_version": "1.0",
        "corpus": dict(baseline["corpus"]),
        "reranker": {
            "model_id": model.model_id,
            "prompt_version": model.prompt_version,
            "policy": "identity_no_provider_call",
        },
        "semantic": semantic,
        "reranked": semantic,
        "comparison": comparison,
        "admission": {
            "admitted": admitted,
            "decision": "admitted" if admitted else "declined",
            "reason": (
                "No metric improved over the admitted semantic baseline; "
                "the only implemented reranker is identity."
            ),
        },
    }


def _render(payload: dict[str, Any]) -> str:
    rows = []
    for name, label, _higher in _COMPARED:
        entry = payload["comparison"][name]
        rows.append(
            f"| {label} | {_metric(entry['semantic'])} |"
            f" {_metric(entry['reranked'])} | {_delta(entry['delta'])} |"
        )
    body = "\n".join(rows)
    corpus = payload["corpus"]
    admission = payload["admission"]
    reranker = payload["reranker"]
    return (
        "# CodeAtlas Phase 7 Rerank A/B\n\n"
        f"- Contract version: `{payload['contract_version']}`\n"
        f"- Query cases: {corpus['query_cases']}\n"
        f"- Change cases: {corpus['change_cases']}\n"
        f"- Reranker: `{reranker['model_id']}`"
        f" / `{reranker['prompt_version']}`\n"
        f"- Admission decision: `{admission['decision']}`\n"
        f"- Reason: {admission['reason']}\n\n"
        "The reranked column applies the only implemented P7-10 reranker,"
        " `NoReranker`, which preserves semantic candidate order and performs"
        " no provider call.\n\n"
        "| Metric | Semantic | Reranked | Delta |\n"
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

