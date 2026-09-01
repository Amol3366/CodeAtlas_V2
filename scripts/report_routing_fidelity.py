"""What does the corpus score when the classifier picks the channel?

``engine_adapter._query_term`` feeds the declared symbol rather than the
question, because Phase 1 measured resolution accuracy and said so. A
consequence recorded but never measured: **the harness bypasses the classifier
by design**, so a question a real user types may reach a different channel than
the one the corpus scored, and no number moves.

DR-09 found the sharp case. The only ``TRACE`` rule is anchored at both ends
and admits one trailing token, so ``Trace the flow from mount.`` reaches the
trace channel while ``Trace order data from frontend to backend.`` falls
through to ``text`` -- a question that literally begins with the verb. On
q032's own fixture the trace channel returns top-1 ``loadOrder`` with both
expected ranges contained, and the text channel a real user reaches ranks
``Order flow`` first and gets top-1 wrong.

This runs the corpus twice. The declared run is today's baseline. The routed
run replaces each case's intent with the channel ``classify(case.question)``
would pick -- **and changes nothing else**. The subject stays the corpus's own,
so the single variable is the channel. Subject extraction is a second axis;
confounding the two would make the delta unreadable.

A question the classifier sends somewhere the corpus has no intent for is
reported as **unroutable** and left as declared rather than scored as a miss.
That is DR-09's ``n/a`` treatment, for its reason: scoring an undefined channel
as a failure invents a disagreement the way ADR-0053's gated intent invented an
average.

**This measures routing, not the fix for it.** Every rule in ``_RULES`` is
anchored at both ends, so trace is one instance of a general shape, and what to
do about that is a ruling this tool exists to inform rather than to pre-empt.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codeatlas.conversations.intent import Intent, classify
from codeatlas.evaluation.dataset import (
    GRAPH_INTENTS,
    Dataset,
    QueryCase,
    load_dataset,
)
from codeatlas.evaluation.engine_adapter import predict_exact_symbols
from codeatlas.evaluation.runner import evaluate_predictions

# Classifier channel -> the corpus intent that reaches the same service call.
# `None` means the corpus has no intent for that channel, so a case routed
# there cannot be scored against anything.
CORPUS_INTENT_BY_CHANNEL: dict[Intent, str | None] = {
    Intent.EXACT_SYMBOL: "EXACT_SYMBOL",
    Intent.CALLERS: "CALLERS",
    Intent.DEPENDENCIES: "DEPENDENCIES",
    Intent.TESTS: "RELATED_TESTS",
    Intent.DOCUMENTS: "DOCUMENT_LOOKUP",
    Intent.TRACE: "TRACE_FLOW",
    # `TEXT` is the lexical fall-through, which is exactly what the adapter's
    # `else` branch calls. `CONCEPTUAL` is the corpus label for that channel.
    Intent.TEXT: "CONCEPTUAL",
    # No corpus intent reaches these channels at all.
    Intent.CALLEES: None,
    Intent.CHANGE: None,
    Intent.GREETING: None,
    Intent.PROJECT_OVERVIEW: None,
}

# ADR-0075: a graph case declares its depth. A rerouted case keeps its own when
# it has one, and takes the documented default when routing makes it a graph
# case for the first time.
_DEFAULT_DEPTH = 2

# `(case_id, declared_intent, routed_intent)`; `None` for an unroutable case.
Moved = tuple[str, str, str | None]


def route(case: QueryCase) -> str | None:
    """The corpus intent the classifier would send this question to."""
    return CORPUS_INTENT_BY_CHANNEL[classify(case.question).intent]


def reroute(dataset: Dataset) -> tuple[Dataset, list[Moved]]:
    """A copy of the corpus routed by the classifier, and what moved.

    The original is never mutated (ADR-0003): rerouting is a measurement, not
    a corpus edit, and a run of this tool must leave `queries.json` untouched.
    """
    routed_cases: list[QueryCase] = []
    moved: list[Moved] = []
    for case in dataset.query_cases:
        target = route(case)
        if target != case.intent:
            moved.append((case.id, case.intent, target))
        if target is None or target == case.intent:
            routed_cases.append(case)
            continue
        depth = case.traversal_depth
        depth = (depth or _DEFAULT_DEPTH) if target in GRAPH_INTENTS else None
        routed_cases.append(
            case.model_copy(update={"intent": target, "traversal_depth": depth})
        )
    return dataset.model_copy(update={"query_cases": routed_cases}), moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("tests/evaluation/cases")
    )
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    routed, moved = reroute(dataset)

    declared = evaluate_predictions(
        dataset, predict_exact_symbols(dataset, record_timings=False)
    )
    actual = evaluate_predictions(
        routed, predict_exact_symbols(routed, record_timings=False)
    )

    unroutable = [item for item in moved if item[2] is None]
    changed = [item for item in moved if item[2] is not None]

    print(f"query cases:                       {len(dataset.query_cases)}")
    print(f"channel changed by the classifier: {len(changed)}")
    print(f"routed to a channel with no intent: {len(unroutable)}")

    if changed:
        print("\nrerouted:")
        for case_id, was, now in changed:
            print(f"  {case_id:6} {was:16} -> {now}")
    if unroutable:
        print("\nunroutable (left as declared, excluded from the delta):")
        for case_id, was, _ in unroutable:
            print(f"  {case_id:6} {was:16} -> {classify_channel(dataset, case_id)}")

    print("\nmetrics:")
    for name in sorted(type(declared.metrics).model_fields):
        before = getattr(declared.metrics, name)
        after = getattr(actual.metrics, name)
        if before is None and after is None:
            continue
        flag = "" if before == after else "   <-- moves"
        print(f"  {name:34} declared={before!s:20} routed={after!s:20}{flag}")
    return 0


def classify_channel(dataset: Dataset, case_id: str) -> str:
    """The raw classifier channel for a case, for reporting an unroutable one."""
    case = next(item for item in dataset.query_cases if item.id == case_id)
    return classify(case.question).intent.value


if __name__ == "__main__":
    raise SystemExit(main())
