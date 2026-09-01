"""Which cases would notice if the ranking were wrong?

Two mutations, per case. **Reverse** inverts the returned symbol order;
**drop-top** removes the first result. A case whose score is unchanged by a
mutation cannot detect that mutation, so it is not measuring what the metric
name suggests.

Measured on 2026-08-15 over the 23 cases added that day: drop-top failed 18,
reverse failed **0** -- because most of those cases return a single symbol, for
which a reversal is a no-op. That count was corrected to 1 of 23 by DR-01b,
because ADR-0059 had made q053 reversal-sensitive two days later and the row
outlived its own number.

**Re-measured because ADR-0075 changed what the question means.** Depth used to
be implied: `GraphQueryRequest.max_depth` defaults to 2, and every graph case
silently took it while ADR-0059 ruled that an expectation declares *direct*
results. So a case declared depth-1 answers and was scored against a depth-2
traversal, and the undeclared second-hop results read as distractors -- which is
exactly what makes a case reversal-sensitive. Now each case declares its depth,
so the distractors are the ones the case asked for.

"Notices" means **the score changed**, not that it got worse. A mutation that
improved a score would be a finding too, and calling it a failure up front would
hide it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codeatlas.evaluation.dataset import Dataset, load_dataset
from codeatlas.evaluation.engine_adapter import predict_exact_symbols
from codeatlas.evaluation.runner import (
    PredictionFile,
    QueryPrediction,
    score_query_case,
)

MUTATIONS = ("reverse", "drop_top")


def mutate(prediction: QueryPrediction, kind: str) -> QueryPrediction:
    """One mutation of a prediction's symbol ranking.

    Returns a copy: the instrument applies both mutations to the same baseline
    prediction, and mutating in place would apply the second to the first one's
    output.
    """
    if kind == "reverse":
        symbols = list(reversed(prediction.ranked_symbols))
    elif kind == "drop_top":
        symbols = list(prediction.ranked_symbols[1:])
    else:
        raise ValueError(f"unknown mutation {kind!r}")
    return prediction.model_copy(update={"ranked_symbols": symbols})


def sensitivity(
    dataset: Dataset, predictions: PredictionFile
) -> dict[str, dict[str, bool]]:
    """Per measured case: did each mutation change its symbol score?

    Unmeasured cases are excluded rather than scored `False`. A case the
    adapter declined to run has no ranking to be sensitive to, and counting it
    as insensitive would understate coverage the way ADR-0024's blurring of
    "not implemented" with "answered wrongly" understated every metric it
    touched.
    """
    by_id = {item.case_id: item for item in predictions.query_predictions}
    result: dict[str, dict[str, bool]] = {}
    for case in dataset.query_cases:
        prediction = by_id.get(case.id)
        if prediction is None:
            continue
        baseline = score_query_case(case, prediction)
        if not baseline.measured:
            continue
        result[case.id] = {
            kind: score_query_case(case, mutate(prediction, kind)).symbols
            != baseline.symbols
            for kind in MUTATIONS
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("tests/evaluation/cases")
    )
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    predictions = predict_exact_symbols(dataset, record_timings=False)
    table = sensitivity(dataset, predictions)
    answers = {
        item.case_id: len(item.ranked_symbols)
        for item in predictions.query_predictions
    }

    print(f"measured cases: {len(table)}\n")
    for kind in MUTATIONS:
        caught = sorted(case_id for case_id, flags in table.items() if flags[kind])
        print(f"{kind}: {len(caught)} of {len(table)} notice")
        print(f"  {', '.join(caught) or '(none)'}\n")

    blind = sorted(
        case_id for case_id, flags in table.items() if not any(flags.values())
    )
    print(f"blind to both: {len(blind)}")
    print(f"  {', '.join(blind) or '(none)'}\n")

    single = sorted(
        case_id for case_id in table if answers.get(case_id, 0) < 2
    )
    print(
        f"answers with fewer than two symbols: {len(single)} "
        "-- a reversal is a no-op for each of these, which is the mechanism "
        "behind the whole row"
    )
    print(f"  {', '.join(single) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
