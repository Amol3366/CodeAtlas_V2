"""CodeAtlas evaluation runner (skeleton — Phase 0).

Runs even with zero features implemented. Today it:

1. loads the hand-authored benchmark datasets (Blueprint §13.6 / Phase 0);
2. validates their structure and that every referenced fixture file exists
   (so the ground truth cannot silently rot);
3. prints per-intent / per-fixture coverage and marks every retrieval and
   change-analysis check as PENDING until the corresponding phase lands.

As phases come online (retrieval in Phase 6, change analysis in Phase 8-10),
wire the real checks into `evaluate_questions` / `evaluate_change_cases` and
replace PENDING with measured pass/fail against the §13.5 targets.

Usage:
    uv run python scripts/run_evaluation.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "tests" / "evaluation"
QUESTIONS_PATH = EVAL_DIR / "benchmark_questions.json"
CHANGE_CASES_PATH = EVAL_DIR / "change_cases.json"

# §13.5 engineering targets, recorded here so the runner documents the gates it
# will enforce once the features exist.
TARGETS = {
    "valid_citations": 1.00,
    "exact_symbol_lookup": 0.98,
    "primary_evidence_recall_at_10": 0.90,
    "unsupported_claim_rate_max": 0.02,
    "working_tree_change_detection": 1.00,
    "active_snapshot_leakage": 0,
}


@dataclass
class Dataset:
    fixtures: dict[str, str]
    items: list[dict]


def _load(path: Path, items_key: str) -> Dataset:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Dataset(fixtures=data["fixtures"], items=data[items_key])


def _fixture_root(fixtures: dict[str, str], fixture_id: str) -> Path:
    if fixture_id not in fixtures:
        raise KeyError(f"unknown fixture id: {fixture_id!r}")
    return REPO_ROOT / fixtures[fixture_id]


def validate_ground_truth(questions: Dataset, change_cases: Dataset) -> list[str]:
    """Return a list of ground-truth problems (empty == valid)."""
    problems: list[str] = []

    for q in questions.items:
        root = _fixture_root(questions.fixtures, q["repository_fixture"])
        for ev in q["required_evidence"]:
            fpath = root / ev["file_path"]
            if not fpath.exists():
                problems.append(f"{q['id']}: missing fixture file {ev['file_path']}")

    for c in change_cases.items:
        root = _fixture_root(change_cases.fixtures, c["repository_fixture"])
        # `add` / rename edits legitimately reference not-yet-existing target files;
        # only validate the files the case says already exist and are edited in place.
        op = c["edit"]["operation"]
        edited = root / c["edit"]["file_path"]
        if op in {"modify_signature", "modify_body", "delete", "move"} and not edited.exists():
            problems.append(f"{c['id']}: edit target missing {c['edit']['file_path']}")
        for tref in c.get("expected_related_tests", []):
            tpath = root / tref["file_path"]
            if not tpath.exists():
                problems.append(f"{c['id']}: related-test file missing {tref['file_path']}")

    return problems


def evaluate_questions(questions: Dataset) -> None:
    by_intent = Counter(q["intent"] for q in questions.items)
    by_fixture = Counter(q["repository_fixture"] for q in questions.items)
    print(f"\nBenchmark questions: {len(questions.items)} (target range 30-50)")
    print("  by intent:  " + ", ".join(f"{k}={v}" for k, v in sorted(by_intent.items())))
    print("  by fixture: " + ", ".join(f"{k}={v}" for k, v in sorted(by_fixture.items())))
    print("  retrieval scoring: PENDING (Phase 6+)")


def evaluate_change_cases(change_cases: Dataset) -> None:
    contract_changes = sum(1 for c in change_cases.items if c.get("expected_contract_change"))
    with_impact = sum(1 for c in change_cases.items if c.get("expected_impact_paths"))
    print(f"\nChange cases: {len(change_cases.items)} (target range 20-30)")
    print(f"  contract-change cases: {contract_changes}")
    print(f"  cases with expected impact paths: {with_impact}")
    print("  change-analysis scoring: PENDING (Phase 8-10)")


def main() -> int:
    print("CodeAtlas evaluation runner (Phase 0 skeleton)")
    print("=" * 60)

    questions = _load(QUESTIONS_PATH, "questions")
    change_cases = _load(CHANGE_CASES_PATH, "cases")

    problems = validate_ground_truth(questions, change_cases)
    if problems:
        print("\nGROUND TRUTH VALIDATION FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nGround-truth validation: OK (all referenced fixture files exist)")

    evaluate_questions(questions)
    evaluate_change_cases(change_cases)

    print("\nEngineering targets (Blueprint 13.5, enforced once features land):")
    for name, target in TARGETS.items():
        print(f"  - {name}: {target}")

    print("\nDone. No feature checks are wired yet; nothing to fail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
