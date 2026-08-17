"""Measure the RRF coarse-chunk bias, and what a granularity penalty costs.

ADR-0028 recorded that reciprocal-rank fusion rewards coarse chunks: a
whole-file chunk matches most queries, appears in both channels, and the rank
sum credits it for being unspecific. ADR-0030 declined to add a penalty until
it was measured "across the corpus, not fitted to one case". ADR-0056 is that
measurement, and this script is how it was taken.

Two modes:

* the default reports **incidence** -- how often a coarse chunk outranks the
  evidence a case declares, and where that evidence lands;
* ``--ab`` reports **effect** -- every metric with the penalty applied at three
  strengths, beside the unpenalised baseline.

Nothing in ``src/`` is modified. The penalty is injected by wrapping
``fuse_ranks`` for the duration of a run, which is deliberate: the standing
rule is to revert a mutation from a file copy because ``git checkout --`` has
twice reverted the fix along with the mutation (ADR-0022, ADR-0042). A wrapper
cannot leave residue at all.

**This script is not in any gate and must not be added to one.** It needs the
`semantic-local` extra, and Section 4.3 forbids making a gate depend on an
optional provider -- the same reason the explanation A/B was removed from
`check_phase7.ps1` and left as a documented manual command.

Usage::

    uv run python scripts/measure_rrf_penalty.py
    uv run python scripts/measure_rrf_penalty.py --ab
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from codeatlas.application import semantic_fusion
from codeatlas.application.container import build_services
from codeatlas.application.rank_fusion import RANK_FUSION_K
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.evaluation.cli import (
    EXIT_INTERNAL_FAILURE,
    EXIT_INVALID_INPUT,
    EXIT_SUCCESS,
)
from codeatlas.evaluation.dataset import Dataset, DatasetError, load_dataset
from codeatlas.evaluation.runner import PredictionFile, evaluate_predictions
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

DEFAULT_DATASET = Path("tests/evaluation/semantic_cases")

# The chunker's own `_CONTAINER_KINDS`. Granularity is read from the chunk's
# declared kind rather than from a size threshold, so "coarse" means what the
# chunking layer already means by it instead of a number chosen here.
COARSE_KINDS = frozenset({"module", "class"})

# Only for a region that is not exactly a symbol range. Arbitrary, and recorded
# as arbitrary in ADR-0056; the conclusion there does not turn on it.
WIDE_SPAN_LINES = 25

METRICS = (
    "containing_evidence_recall_at_10",
    "primary_evidence_recall_at_10",
    "symbol_recall_at_10",
    "mean_reciprocal_rank",
    "ndcg_at_10",
    "containing_evidence_rate",
    "exact_evidence_rate",
    "abstention_correctness",
)

Region = tuple[str, int, int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the RRF coarse-chunk bias and the penalty's cost."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--ab",
        action="store_true",
        help="Also run the penalty A/B at three strengths.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Write the full per-case detail here.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        dataset = load_dataset(args.dataset)
        fixture = _only_fixture(dataset)
        kinds = _symbol_kinds(args.dataset / "fixtures" / fixture)

        payload: dict[str, Any] = {"incidence": _incidence(dataset, kinds)}
        _print_incidence(payload["incidence"])
        if args.ab:
            payload["ab"] = _ab(dataset, kinds)
            _print_ab(payload["ab"])

        if args.json_output is not None:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        return EXIT_SUCCESS
    except (DatasetError, OSError, json.JSONDecodeError) as error:
        print(f"Invalid input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        print(f"Internal measurement failure: {error}", file=sys.stderr)
        return EXIT_INTERNAL_FAILURE


def _only_fixture(dataset: Dataset) -> str:
    """The fixture every case shares, refusing if they do not share one.

    Guessing would silently measure one fixture's chunk kinds against another
    fixture's answers, which reads as a result rather than as a mistake.
    """
    fixtures = {case.repository_fixture for case in dataset.query_cases}
    if len(fixtures) != 1:
        raise DatasetError(
            "this measurement assumes one fixture; got "
            f"{sorted(fixtures)}. Extend it before measuring a mixed corpus."
        )
    return fixtures.pop()


def _symbol_kinds(fixture_root: Path) -> dict[Region, str]:
    """Index the fixture once to learn each region's declared symbol kind.

    A separate database, because the evaluation harness destroys its own.
    Indexing is deterministic by contract, so these ranges are the ranges the
    measured run saw.
    """
    with (
        tempfile.TemporaryDirectory(prefix="codeatlas-rrf-kinds-") as workspace,
        connect(Path(workspace) / "kinds.sqlite") as connection,
    ):
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(fixture_root))
        )
        services.indexing.index(repository.repository_id)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT f.relative_path AS path, s.kind AS kind,
                   s.start_line AS start_line, s.end_line AS end_line
            FROM symbols s
            JOIN files f ON f.file_id = s.file_id
            JOIN snapshots snap ON snap.snapshot_id = s.snapshot_id
            WHERE snap.state = 'active'
            """
        ).fetchall()
    return {
        (_norm(row["path"]), row["start_line"], row["end_line"]): str(
            row["kind"]
        ).lower()
        for row in rows
    }


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _is_coarse(region: Region, kinds: dict[Region, str]) -> bool:
    path, start, end = region
    kind = kinds.get((_norm(path), start, end))
    if kind is not None:
        return kind in COARSE_KINDS
    return (end - start + 1) >= WIDE_SPAN_LINES


def _contains(region: Region, path: str, start: int, end: int) -> bool:
    region_path, region_start, region_end = region
    return (
        _norm(region_path) == _norm(path)
        and region_start <= start
        and region_end >= end
    )


def _incidence(dataset: Dataset, kinds: dict[Region, str]) -> list[dict[str, Any]]:
    """How often a coarse chunk outranks the evidence a case declares."""
    from codeatlas.evaluation.engine_adapter import predict_conceptual

    result = predict_conceptual(dataset, semantic=True, record_timings=False)
    by_case = {p.case_id: p for p in result.query_predictions}

    rows: list[dict[str, Any]] = []
    for case in dataset.query_cases:
        prediction = by_case.get(case.id)
        ranked = list(prediction.ranked_evidence) if prediction is not None else []
        expected = case.expected_evidence[0] if case.expected_evidence else None

        evidence_rank: int | None = None
        coarse_above = 0
        if expected is not None:
            for rank, item in enumerate(ranked, start=1):
                region: Region = (item.file_path, item.start_line, item.end_line)
                if _contains(
                    region, expected.file_path, expected.start_line, expected.end_line
                ):
                    evidence_rank = rank
                    break
                if _is_coarse(region, kinds):
                    coarse_above += 1

        symbol_rank: int | None = None
        wanted = set(case.expected_symbols or ())
        for rank, symbol in enumerate(
            prediction.ranked_symbols if prediction is not None else [], start=1
        ):
            if symbol in wanted:
                symbol_rank = rank
                break

        rows.append(
            {
                "case": case.id,
                "expected_evidence": (
                    f"{expected.file_path}:{expected.start_line}-{expected.end_line}"
                    if expected is not None
                    else None
                ),
                "evidence_rank": evidence_rank,
                "symbol_rank": symbol_rank,
                "coarse_above_expected": coarse_above,
                "returned": len(ranked),
            }
        )
    return rows


def _penalised_fuse(
    kinds: dict[Region, str], mode: str, strength: float
) -> Callable[[Iterable[Region], Iterable[Region]], list[Region]]:
    """A `fuse_ranks` that demotes coarse chunks, by `mode`."""

    def fuse(
        deterministic: Iterable[Region], semantic: Iterable[Region]
    ) -> list[Region]:
        ordered_deterministic = list(dict.fromkeys(deterministic))
        ordered_semantic = list(dict.fromkeys(semantic))
        scores: dict[Region, float] = {}
        for channel in (ordered_deterministic, ordered_semantic):
            for rank, item in enumerate(channel, start=1):
                scores[item] = scores.get(item, 0.0) + 1.0 / (RANK_FUSION_K + rank)

        candidates = ordered_deterministic + [
            item
            for item in ordered_semantic
            if item not in set(ordered_deterministic)
        ]
        if mode == "partition":
            return sorted(
                candidates,
                key=lambda item: (_is_coarse(item, kinds), -scores[item]),
            )
        return sorted(
            candidates,
            key=lambda item: -(
                scores[item] * (strength if _is_coarse(item, kinds) else 1.0)
            ),
        )

    return fuse


def _ab(dataset: Dataset, kinds: dict[Region, str]) -> dict[str, dict[str, Any]]:
    """Every metric, unpenalised and at three penalty strengths.

    Three rather than one because ADR-0028 rejected channel weighting as "a
    constant nobody can later justify"; a result that held only at one
    arbitrary constant would repeat that mistake.
    """
    from codeatlas.evaluation.engine_adapter import predict_changes, predict_conceptual

    variants: tuple[tuple[str, str, float], ...] = (
        ("baseline", "none", 1.0),
        ("scale 0.50", "scale", 0.50),
        ("scale 0.25", "scale", 0.25),
        ("fine-first", "partition", 1.0),
    )

    # Replaced by name rather than by attribute access. The penalty has to
    # displace the binding *inside* `semantic_fusion`, because that is the name
    # the service calls; `fuse_ranks` is imported there rather than exported
    # from there, so a static reference would be reaching through a module that
    # does not publish it.
    attribute = "fuse_ranks"
    results: dict[str, dict[str, Any]] = {}
    original: Any = getattr(semantic_fusion, attribute)
    for label, mode, strength in variants:
        print(f"running {label} ...", flush=True)
        if mode != "none":
            setattr(semantic_fusion, attribute, _penalised_fuse(kinds, mode, strength))
        try:
            queries = predict_conceptual(
                dataset, semantic=True, record_timings=False
            )
            changes = predict_changes(dataset, record_timings=False)
            report = evaluate_predictions(
                dataset,
                PredictionFile(
                    implementation_status="implemented",
                    query_predictions=queries.query_predictions,
                    change_predictions=changes.change_predictions,
                ),
            )
        finally:
            setattr(semantic_fusion, attribute, original)
        results[label] = {
            metric: getattr(report.metrics, metric, None) for metric in METRICS
        }
    return results


def _print_incidence(rows: list[dict[str, Any]]) -> None:
    print(f"\nIncidence over {len(rows)} cases\n")
    header = f"{'case':<6} {'ev@':>5} {'sym@':>5} {'coarse>ev':>10}  expected"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['case']:<6} {row['evidence_rank']!s:>5}"
            f" {row['symbol_rank']!s:>5} {row['coarse_above_expected']:>10}"
            f"  {row['expected_evidence']}"
        )
    hurt = [r for r in rows if r["coarse_above_expected"] > 0]
    print(f"\ncoarse chunk outranks the declared evidence in {len(hurt)} case(s)")


def _print_ab(results: dict[str, dict[str, Any]]) -> None:
    labels = list(results)
    width = max(len(m) for m in METRICS) + 2
    header = f"{'metric':<{width}}" + "".join(f"{label:>16}" for label in labels)
    print(f"\n{header}")
    print("-" * len(header))
    for metric in METRICS:
        base = results["baseline"][metric]
        line = f"{metric:<{width}}"
        for label in labels:
            value = results[label][metric]
            if value is None:
                line += f"{'n/a':>16}"
            elif label == "baseline":
                line += f"{value:>16.4f}"
            else:
                line += f"{value:>10.4f}{value - base:>+7.4f}".rjust(16)
        print(line)


if __name__ == "__main__":
    raise SystemExit(main())
