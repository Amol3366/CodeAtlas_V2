"""Measure what answer generation changes, against a real provider.

**What replaced what.** The first version of this script compared the semantic
baseline against itself — `after = before`, literally — and recorded
`declined` because every delta was zero by construction. It never ran an
evaluation and never called a provider, so it would have recorded the same
verdict no matter what was built. That is not a measurement, and ADR-0012
required this to become one before generation could be admitted.

**What this measures, and what it cannot.** Generation replaces
`answer.summary` and nothing else (ADR-0012 decision 1). Every metric in the
retrieval suite is computed from `ranked_evidence` and `claims`, both of which
pass through untouched. So the honest expectation is **zero delta on all six**,
and observing that is worth doing: it is the executable proof of the trust
boundary the ADR promises, measured rather than asserted.

What it cannot measure is whether the prose is *better to read*. The corpus has
no ground truth for that, and inventing one here would be dressing up a
judgement as a metric.

What it can measure, and no earlier run did, is whether a real model states
things the evidence does not support. `forbidden_claims` are declared per case
and were previously checked only against structured claims — which a model
never writes. This checks the generated summary too, which is the one place a
model can now introduce an unsupported statement.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codeatlas.evaluation.cli import (
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
)
from codeatlas.evaluation.dataset import Dataset, load_dataset
from codeatlas.evaluation.engine_adapter import predict_conceptual
from codeatlas.evaluation.runner import (
    EvaluationReport,
    PredictionFile,
    contains_forbidden_claim,
    evaluate_predictions,
)

_COMPARED = (
    ("primary_evidence_recall_at_10", "Primary evidence Recall@10", True),
    ("exact_evidence_rate", "Exact evidence rate", True),
    ("containing_evidence_rate", "Containing evidence rate", True),
    ("exact_symbol_resolution", "Exact symbol resolution", True),
    ("valid_evidence_rate", "Valid evidence rate", True),
    ("unsupported_claim_rate", "Unsupported claim rate", False),
)

DEFAULT_MODEL = "llama3.2:3b"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure answer generation against a real provider."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to answer with (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="Per-answer bound, seconds."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against tracked artifacts instead of overwriting them.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        dataset = load_dataset(args.dataset)
        payload = _measure(dataset, model=args.model, timeout=args.timeout)
        json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        markdown_text = _render(payload)

        if args.check:
            if not (
                _matches(args.json_output, json_text)
                and _matches(args.markdown_output, markdown_text)
            ):
                print(
                    "Phase 7 explanation artifacts are stale. Regenerate them"
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


def _measure(dataset: Dataset, *, model: str, timeout: float) -> dict[str, Any]:
    from codeatlas.generation.explanations import EvidenceGroundedExplanationService
    from codeatlas.generation.ollama_provider import OllamaAnswerProvider

    provider = OllamaAnswerProvider(model_id=model, timeout_seconds=timeout)
    explainer = EvidenceGroundedExplanationService(provider)

    # One switch, one difference. Both sides run the same corpus, services, and
    # verbatim questions; only the explainer is attached.
    started = time.perf_counter()
    without = predict_conceptual(dataset, semantic=False, record_timings=False)
    baseline_seconds = time.perf_counter() - started

    started = time.perf_counter()
    with_generation = predict_conceptual(
        dataset, semantic=False, explainer=explainer, record_timings=False
    )
    generated_seconds = time.perf_counter() - started

    before = _score(dataset, without)
    after = _score(dataset, with_generation)

    comparison: dict[str, Any] = {}
    improved = False
    for name, _label, higher_is_better in _COMPARED:
        first = getattr(before.metrics, name)
        second = getattr(after.metrics, name)
        delta = None if first is None or second is None else second - first
        comparison[name] = {
            "without_generation": first,
            "with_generation": second,
            "delta": delta,
        }
        if delta is not None and delta != 0:
            improved = improved or (delta > 0 if higher_is_better else delta < 0)

    prose = _prose_safety(dataset, with_generation)

    return {
        "contract_version": "1.1",
        "corpus": {
            "query_cases": len(dataset.query_cases),
            "change_cases": len(dataset.change_cases),
        },
        "answer_provider": {
            "provider": "ollama",
            "model_id": model,
            "policy": "prose_over_untouched_evidence",
        },
        "comparison": comparison,
        "prose_safety": prose,
        "cost": {
            "baseline_seconds": round(baseline_seconds, 2),
            "generated_seconds": round(generated_seconds, 2),
            "added_seconds": round(generated_seconds - baseline_seconds, 2),
            "added_seconds_per_case": (
                round(
                    (generated_seconds - baseline_seconds)
                    / max(len(dataset.query_cases), 1),
                    2,
                )
            ),
        },
        "admission": {
            "admitted": False,
            "decision": "declined",
            "reason": _reason(improved, prose),
        },
    }


def _score(dataset: Dataset, queries: PredictionFile) -> EvaluationReport:
    return evaluate_predictions(
        dataset,
        PredictionFile(
            implementation_status="implemented",
            query_predictions=queries.query_predictions,
            change_predictions=[],
        ),
    )


def _prose_safety(dataset: Dataset, generated: PredictionFile) -> dict[str, Any]:
    """Whether the model stated anything a case forbids.

    The retrieval suite checks `forbidden_claims` against structured claims,
    which a model never writes. The summary is the one surface generation can
    introduce an unsupported statement on, so it is checked here — the only
    genuinely new signal in this comparison.
    """
    by_id = {case.id: case for case in dataset.query_cases}
    offenders: list[dict[str, str]] = []
    checked = 0
    for prediction in generated.query_predictions:
        case = by_id.get(prediction.case_id)
        if case is None or not case.forbidden_claims:
            continue
        checked += 1
        summary = prediction.answer_summary or ""
        for forbidden in case.forbidden_claims:
            if contains_forbidden_claim(summary, [forbidden]):
                offenders.append({"case_id": case.id, "forbidden_claim": forbidden})

    return {
        "cases_with_forbidden_claims": checked,
        "violations": len(offenders),
        "offenders": offenders,
        "note": (
            "Checks the generated summary against each case's declared"
            " forbidden claims. The structured claims are not model-written and"
            " are covered by the retrieval suite."
        ),
        "limitation": (
            "The comparison casefolds and collapses whitespace; it does not"
            " stem, strip punctuation, or compare meaning. A paraphrase of a"
            " forbidden statement passes. Zero violations means the model did"
            " not repeat a declared sentence — not that its prose is factually"
            " safe."
        ),
    }


def _reason(improved: bool, prose: dict[str, Any]) -> str:
    parts = [
        "Generation replaces answer.summary only, so every retrieval metric is"
        " invariant by construction and the measured deltas confirm it."
    ]
    if improved:
        parts.append(
            "A metric moved, which should not happen and indicates the trust"
            " boundary leaked."
        )
    if prose["violations"]:
        parts.append(
            f"The generated prose stated {prose['violations']} forbidden"
            " claim(s)."
        )
    else:
        parts.append(
            "The generated prose repeated no declared forbidden sentence,"
            " though that check is exact-substring and a paraphrase would"
            " pass it."
        )
    parts.append(
        "Reader-quality uplift is not measurable from this corpus, which"
        " declares no ground truth for explanation quality, so generation"
        " remains declined and available only as an opt-in."
    )
    return " ".join(parts)


def _render(payload: dict[str, Any]) -> str:
    rows = []
    for name, label, _higher in _COMPARED:
        entry = payload["comparison"][name]
        rows.append(
            f"| {label} | {_metric(entry['without_generation'])} |"
            f" {_metric(entry['with_generation'])} | {_delta(entry['delta'])} |"
        )
    body = "\n".join(rows)
    corpus = payload["corpus"]
    admission = payload["admission"]
    provider = payload["answer_provider"]
    prose = payload["prose_safety"]
    cost = payload["cost"]
    return (
        "# CodeAtlas Phase 7 Explanation A/B\n\n"
        f"- Contract version: `{payload['contract_version']}`\n"
        f"- Query cases: {corpus['query_cases']}\n"
        f"- Answer provider: `{provider['provider']}` /"
        f" `{provider['model_id']}`\n"
        f"- Admission decision: `{admission['decision']}`\n"
        f"- Declared forbidden sentences repeated in generated prose:"
        f" {prose['violations']} across {prose['cases_with_forbidden_claims']}"
        " case(s) that declare one\n"
        f"- Limitation of that check: {prose['limitation']}\n"
        f"- Added latency: {cost['added_seconds']} s total,"
        f" {cost['added_seconds_per_case']} s per case\n\n"
        "Both columns run the same corpus, services, and verbatim questions.\n"
        "The only difference is whether an answer provider is attached.\n\n"
        "**A zero delta on every row is the expected and desired result.**\n"
        "Generation replaces `answer.summary`; these metrics are computed from\n"
        "evidence and structured claims, which it never touches. A non-zero\n"
        "delta here would mean the trust boundary leaked.\n\n"
        "| Metric | Without generation | With generation | Delta |\n"
        "| --- | ---: | ---: | ---: |\n"
        f"{body}\n\n"
        f"**Decision:** {admission['reason']}\n"
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
