"""Phase 0 exit-criteria tests for the hand-authored evaluation datasets.

These assert the dataset *shape* and that every fixture file the ground truth
references actually exists — so the truth cannot silently rot as fixtures evolve.
"""

from __future__ import annotations

import json
from pathlib import Path

from codeatlas.domain.enums import ChangeKind, FindingCategory, IntentType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "tests" / "evaluation"
VALID_INTENTS = {i.value for i in IntentType}
VALID_CHANGE_KINDS = {c.value for c in ChangeKind}
VALID_FINDING_CATEGORIES = {f.value for f in FindingCategory}


def _load(name: str) -> dict:
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))


def _fixture_root(fixtures: dict[str, str], fixture_id: str) -> Path:
    assert fixture_id in fixtures, f"unknown fixture id {fixture_id!r}"
    return REPO_ROOT / fixtures[fixture_id]


def test_benchmark_questions_count_in_range() -> None:
    data = _load("benchmark_questions.json")
    assert 30 <= len(data["questions"]) <= 50


def test_benchmark_question_ids_unique() -> None:
    data = _load("benchmark_questions.json")
    ids = [q["id"] for q in data["questions"]]
    assert len(ids) == len(set(ids))


def test_benchmark_questions_reference_existing_fixture_files() -> None:
    data = _load("benchmark_questions.json")
    for q in data["questions"]:
        assert q["intent"] in VALID_INTENTS, q["id"]
        root = _fixture_root(data["fixtures"], q["repository_fixture"])
        assert q["required_evidence"], f"{q['id']} has no required evidence"
        for ev in q["required_evidence"]:
            assert (root / ev["file_path"]).exists(), f"{q['id']}: {ev['file_path']}"


def test_change_cases_count_in_range() -> None:
    data = _load("change_cases.json")
    assert 20 <= len(data["cases"]) <= 30


def test_change_case_ids_unique() -> None:
    data = _load("change_cases.json")
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids))


def test_change_cases_are_well_formed() -> None:
    data = _load("change_cases.json")
    for c in data["cases"]:
        root = _fixture_root(data["fixtures"], c["repository_fixture"])
        for sym in c["expected_changed_symbols"]:
            assert sym["change_kind"] in VALID_CHANGE_KINDS, c["id"]
        for cat in c.get("expected_findings", []):
            assert cat in VALID_FINDING_CATEGORIES, f"{c['id']}: {cat}"
        # In-place edits must target a file that exists today.
        if c["edit"]["operation"] in {"modify_signature", "modify_body", "delete", "move"}:
            assert (root / c["edit"]["file_path"]).exists(), c["id"]
        for tref in c.get("expected_related_tests", []):
            assert (root / tref["file_path"]).exists(), f"{c['id']}: {tref['file_path']}"


def test_change_cases_cover_all_change_kinds() -> None:
    data = _load("change_cases.json")
    seen = {sym["change_kind"] for c in data["cases"] for sym in c["expected_changed_symbols"]}
    assert seen == VALID_CHANGE_KINDS


def test_at_least_one_contract_change_case() -> None:
    data = _load("change_cases.json")
    assert any(c.get("expected_contract_change") for c in data["cases"])
