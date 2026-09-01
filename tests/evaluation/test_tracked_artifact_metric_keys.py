"""Every regenerable tracked artifact carries the whole metric key set.

**This defect has occurred twice with an identical signature**, and both times
the artifact was repaired while the mechanism was left alone:

* 2026-08-16 -- `finding_count_correctness` entered `AggregateMetrics` on
  2026-08-14; `baseline-phase-7.json` and `rerank-phase-7.json` were never
  regenerated and `--check` exited 5.
* 2026-09-02 (DR-01b) -- `changed_symbol_exact_cases` entered the model on
  2026-08-20; the same two artifacts, the same exit 5, the same "two added
  lines, no value change" diff.

**The mechanism is a backward-compatibility default doing its job.** Each new
field is declared `= None` so an artifact written before that field still loads
and scores exactly as it did (ADR-0027's and ADR-0038's pattern, and the right
call). The cost is that a *missing* key is indistinguishable from a key whose
value is genuinely unknown, so nothing objects until a `--check` compares bytes.

**Why the existing `--check` steps are not enough.** They live behind
`check_phase7.ps1 -Semantic`, which needs the optional extras and is opt-in --
the register calls it "the flag that goes unrun". Worse, the two artifacts fail
*in sequence*: both times `rerank-phase-7.json` was discovered only after
`baseline-phase-7.json` was fixed, because the gate stops at the first failure.
A hidden queue, not a single item.

This test needs no extras and reads no model, so it runs in **every** gate. It
would have caught both occurrences on the day the field landed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codeatlas.evaluation.runner import AggregateMetrics

_ARTIFACT_ROOT = Path("docs/evaluation")

# Artifacts deliberately frozen at the state their gate was approved on.
# ADR-0017: `check_phase1.ps1` and `check_phase2.ps1` are SUPERSEDED and exit 5
# by design, so regenerating these would overwrite the record those gates were
# approved against. They are exempt from the key set, not from review.
_FROZEN: frozenset[str] = frozenset(
    {"baseline-phase-1.json", "baseline-phase-2.json"}
)


def _metrics_blocks(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every ``metrics`` mapping in a document, with a locating path.

    Recursive because Phase 7 nests two whole reports under `deterministic` and
    `semantic`, and the rerank A/B nests `semantic` and `reranked`. A top-level
    lookup would have checked the Phase 0-4 artifacts and silently skipped
    exactly the two that went stale.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        metrics = node.get("metrics")
        if isinstance(metrics, dict):
            found.append((path or "root", metrics))
        for key, value in node.items():
            found.extend(_metrics_blocks(value, f"{path}.{key}" if path else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_metrics_blocks(value, f"{path}[{index}]"))
    return found


def _tracked_artifacts() -> list[Path]:
    return sorted(
        path
        for path in _ARTIFACT_ROOT.glob("*.json")
        if path.name not in _FROZEN
    )


def test_there_are_artifacts_with_metrics_to_check() -> None:
    """Guard the guard.

    The assertion below passes vacuously if the glob matches nothing or if no
    file carries a metrics block -- a directory rename would disable the real
    check without failing anything.
    """
    with_metrics = [
        path
        for path in _tracked_artifacts()
        if _metrics_blocks(json.loads(path.read_text(encoding="utf-8")))
    ]
    assert len(with_metrics) >= 5, (
        f"only {len(with_metrics)} tracked artifacts with a metrics block were "
        f"found under {_ARTIFACT_ROOT}; the path has probably moved"
    )


def test_every_regenerable_artifact_carries_the_full_metric_key_set() -> None:
    """A missing key means the artifact predates a field and was never redone.

    Reported per file *and* per nested block, because the failure mode is one
    artifact lagging while its neighbours are current -- naming only the file
    would leave a reader guessing which of two nested reports is stale.
    """
    expected = set(AggregateMetrics.model_fields)
    missing: dict[str, list[str]] = {}

    for path in _tracked_artifacts():
        document = json.loads(path.read_text(encoding="utf-8"))
        for location, metrics in _metrics_blocks(document):
            absent = sorted(expected - set(metrics))
            if absent:
                missing[f"{path.name}::{location}"] = absent

    assert not missing, (
        "these tracked artifacts are missing metric keys, which means a field "
        "was added to AggregateMetrics and they were never regenerated:\n"
        + "\n".join(
            f"  {where}: {', '.join(keys)}" for where, keys in sorted(missing.items())
        )
        + "\nRegenerate each one without --check and commit the diff for review "
        "(ADR-0022: a gated artifact that stops reproducing is reviewed, not "
        "absorbed)."
    )


def test_the_frozen_artifacts_are_named_rather_than_pattern_matched() -> None:
    """An exemption has to be argued for, so it cannot grow by accident.

    `_FROZEN` is an explicit two-item set citing ADR-0017. A glob such as
    "skip phases 0-2" would silently absorb a future artifact that merely
    looked similar, which is how the corpus fixture tuple in `engine_adapter`
    understated two metrics for four phases.
    """
    assert sorted(_FROZEN) == ["baseline-phase-1.json", "baseline-phase-2.json"]
    for name in _FROZEN:
        assert (_ARTIFACT_ROOT / name).exists(), (
            f"{name} is exempted but does not exist; remove the exemption "
            "rather than leaving it to match nothing"
        )
