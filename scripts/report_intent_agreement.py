"""Does a corpus case's declared intent agree with the product's classifier?

DR-09 was authorised by ADR-0073 ruling 4 to audit the ``TRACE_FLOW`` label,
which a Deferred Register row had called "systemically wrong" on the evidence of
three cases. The audit needed a control the row never had: **how the other
intents score on the same question.** They score worse. ``EXACT_SYMBOL``, the
largest intent in the corpus, agrees with ``classify()`` on **0 of 36** cases.

That is by design, not by defect, and the design is recorded at
``engine_adapter._query_term``: the harness feeds the declared symbol rather
than the question, because it measures resolution accuracy and not question
understanding. **A declared intent names the channel under measurement; it is
not a prediction of what the classifier would return.** Corpus questions are
natural language ("What validates the capture key?") while the classifier's
rules are command-shaped ("who calls X"), so disagreement is the normal case.

The tool exists because this row has now carried a wrong count twice -- "six
cases" when ADR-0051 had already re-typed one of them, and "every one checked"
when one of five agrees. A claim about agreement is made by running this, not by
reading the corpus and reasoning about it.

An intent with no classifier channel (``CONFIG_LOOKUP``, ``CONCEPTUAL``,
``EXPORTS``, ``POLICY``) is reported as ``n/a`` rather than as a disagreement:
there is no channel it could have agreed with, and scoring it as a miss would
invent a disagreement the way ADR-0053's gated intent invented an average.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections import Counter
from pathlib import Path

from codeatlas.conversations.intent import classify
from codeatlas.evaluation.dataset import load_dataset

# Corpus intent -> the `Intent` value `classify()` would have to return to
# agree. `None` means the classifier has no channel for that intent at all, so
# agreement is undefined rather than false.
_CHANNEL_BY_INTENT: dict[str, str | None] = {
    "EXACT_SYMBOL": "exact_symbol",
    "CALLERS": "callers",
    "DEPENDENCIES": "dependencies",
    "RELATED_TESTS": "tests",
    "DOCUMENT_LOOKUP": "documents",
    "TRACE_FLOW": "trace",
    "CONFIG_LOOKUP": None,
    "CONCEPTUAL": None,
    "EXPORTS": None,
    "POLICY": None,
}


@dataclasses.dataclass(frozen=True)
class IntentAgreement:
    """One declared intent, and how often the classifier would produce it."""

    intent: str
    cases: int
    agreeing: int | None
    returned: dict[str, int]


def report_agreement(dataset_root: Path) -> list[IntentAgreement]:
    """Agreement between each declared intent and `classify()`, per intent."""
    dataset = load_dataset(dataset_root)
    by_intent: dict[str, list[str]] = {}
    for case in dataset.query_cases:
        by_intent.setdefault(case.intent, []).append(
            classify(case.question).intent.value
        )

    reports: list[IntentAgreement] = []
    for intent in sorted(by_intent):
        returned = by_intent[intent]
        channel = _CHANNEL_BY_INTENT.get(intent)
        reports.append(
            IntentAgreement(
                intent=intent,
                cases=len(returned),
                agreeing=(
                    None
                    if channel is None
                    else sum(value == channel for value in returned)
                ),
                returned=dict(Counter(returned)),
            )
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("tests/evaluation/cases"),
        help="corpus root holding queries.json (default: the retrieval corpus)",
    )
    arguments = parser.parse_args()

    reports = report_agreement(arguments.dataset)
    print(f"{'declared intent':16} {'cases':>5} {'agrees':>8}   classify() returned")
    print("-" * 92)
    for report in reports:
        agrees = (
            "n/a"
            if report.agreeing is None
            else f"{report.agreeing}/{report.cases}"
        )
        print(f"{report.intent:16} {report.cases:>5} {agrees:>8}   {report.returned}")

    scored = [item for item in reports if item.agreeing is not None]
    total = sum(item.cases for item in scored)
    agreeing = sum(item.agreeing or 0 for item in scored)
    print("-" * 92)
    print(f"{'TOTAL (scored)':16} {total:>5} {f'{agreeing}/{total}':>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
