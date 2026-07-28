from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import DatasetError, load_dataset


def test_change_evidence_validates_against_base_state(tmp_path: Path) -> None:
    dataset_root = _dataset_with_side_dirs(tmp_path)
    dataset = load_dataset(dataset_root)

    case = dataset.change_cases[0]
    assert case.base_state.root == (
        dataset_root / "fixtures" / "sample" / "base"
    )
    assert case.base_state.overlay is None
    assert case.base_state.label_prefix == "base/"
    assert case.target_state.root == (
        dataset_root / "fixtures" / "sample" / "target"
    )
    assert case.target_state.label_prefix == "target/"
    (evidence,) = case.expected_evidence
    assert evidence.snapshot_id == "snapshot-1-base"
    assert evidence.validated_line_count == 1


def test_change_evidence_validates_against_target_state(tmp_path: Path) -> None:
    dataset_root = _dataset_with_side_dirs(tmp_path)
    changes_path = dataset_root / "changes.json"
    payload = json.loads(changes_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_evidence"][0]["snapshot_id"] = "snapshot-1"
    payload["cases"][0]["expected_evidence"][0]["end_line"] = 2
    changes_path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = load_dataset(dataset_root)

    (evidence,) = dataset.change_cases[0].expected_evidence
    assert evidence.snapshot_id == "snapshot-1"
    assert evidence.validated_line_count == 2


def test_working_tree_variant_validates_against_overlay(
    tmp_path: Path,
) -> None:
    dataset_root = _dataset_with_working_tree_variant(tmp_path)
    dataset = load_dataset(dataset_root)

    case = dataset.change_cases[0]
    assert case.base_state.root == dataset_root / "fixtures" / "sample"
    assert case.base_state.overlay is None
    assert case.target_state.root == dataset_root / "fixtures" / "sample"
    assert case.target_state.overlay == (
        dataset_root / "variants" / "sample" / "add-line" / "target"
    )
    (evidence,) = case.expected_evidence
    assert evidence.validated_line_count == 2


def test_change_evidence_rejects_missing_overlay_file(
    tmp_path: Path,
) -> None:
    dataset_root = _dataset_with_working_tree_variant(tmp_path)
    changes_path = dataset_root / "changes.json"
    payload = json.loads(changes_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_evidence"][0]["file_path"] = "missing.py"
    changes_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="evidence is not a file"):
        load_dataset(dataset_root)


def test_change_evidence_rejects_traversal_out_of_overlay(
    tmp_path: Path,
) -> None:
    dataset_root = _dataset_with_working_tree_variant(tmp_path)
    changes_path = dataset_root / "changes.json"
    payload = json.loads(changes_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_evidence"][0]["file_path"] = "../outside.py"
    changes_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="repository-relative"):
        load_dataset(dataset_root)


def test_variants_root_outside_dataset_root_is_rejected(
    tmp_path: Path,
) -> None:
    dataset_root = _dataset_with_side_dirs(tmp_path)
    manifest_path = dataset_root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["variants_root"] = "../outside_variants"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetError, match="repository-relative"):
        load_dataset(dataset_root)


def test_variants_root_junction_escape_is_rejected(tmp_path: Path) -> None:
    dataset_root = _dataset_with_side_dirs(tmp_path)
    outside = tmp_path / "outside_variants"
    outside.mkdir()
    link = dataset_root / "variants"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(outside, link, target_is_directory=True)

    with pytest.raises(DatasetError, match="repository-relative"):
        load_dataset(dataset_root)


def test_variants_are_invisible_to_query_cases(tmp_path: Path) -> None:
    dataset_root = _dataset_with_working_tree_variant(tmp_path)
    dataset = load_dataset(dataset_root)

    query_case = dataset.query_cases[0]
    (evidence,) = query_case.expected_evidence
    assert evidence.validated_line_count == 1


def _dataset_with_side_dirs(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "cases"
    dataset_root.mkdir()
    fixture_root = dataset_root / "fixtures" / "sample"
    (fixture_root / "base").mkdir(parents=True)
    (fixture_root / "target").mkdir(parents=True)
    (fixture_root / "module.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (fixture_root / "base" / "module.py").write_text(
        "BASE = 1\n", encoding="utf-8"
    )
    (fixture_root / "target" / "module.py").write_text(
        "TARGET = 1\nEXTRA = 2\n", encoding="utf-8"
    )

    manifest = {
        "contract_version": "1.0",
        "fixtures_root": "fixtures",
        "variants_root": "variants",
        "fixtures": [
            {
                "id": "sample",
                "root": "sample",
                "kind": "python",
                "snapshots": [
                    {"id": "snapshot-1", "members": ["module.py"]},
                    {"id": "snapshot-1-base", "members": ["module.py"]},
                ],
            }
        ],
        "query_cases_file": "queries.json",
        "change_cases_file": "changes.json",
        "expected_query_count": 1,
        "expected_change_count": 1,
    }
    shared_evidence = [
        {
            "evidence_id": "evidence-1",
            "snapshot_id": "snapshot-1-base",
            "file_path": "module.py",
            "symbol": "module.BASE",
            "start_line": 1,
            "end_line": 1,
        }
    ]
    query_case = {
        "id": "q1",
        "repository_fixture": "sample",
        "snapshot_id": "snapshot-1",
        "question": "Where is module?",
        "intent": "EXACT_SYMBOL",
        "expected_abstention": False,
        "expected_symbols": ["module.BASE"],
        "expected_relations": [],
        "expected_evidence": [
            {
                "evidence_id": "evidence-1",
                "snapshot_id": "snapshot-1",
                "file_path": "module.py",
                "symbol": "module.VALUE",
                "start_line": 1,
                "end_line": 1,
            }
        ],
        "warnings": [],
        "limitations": [],
        "forbidden_claims": [],
    }
    change_case = {
        "id": "c1",
        "repository_fixture": "sample",
        "snapshot_id": "snapshot-1",
        "base_ref": "base",
        "target_ref": "target",
        "expected_symbols": ["module.BASE"],
        "expected_relations": [],
        "expected_evidence": shared_evidence,
        "expected_changed_symbols": ["module.BASE"],
        "expected_impact_paths": [],
        "expected_findings": [],
        "warnings": [],
        "limitations": [],
        "forbidden_claims": [],
    }
    (dataset_root / "dataset.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (dataset_root / "queries.json").write_text(
        json.dumps({"contract_version": "1.0", "cases": [query_case]}),
        encoding="utf-8",
    )
    (dataset_root / "changes.json").write_text(
        json.dumps({"contract_version": "1.0", "cases": [change_case]}),
        encoding="utf-8",
    )
    return dataset_root


def _dataset_with_working_tree_variant(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "cases"
    dataset_root.mkdir()
    fixture_root = dataset_root / "fixtures" / "sample"
    fixture_root.mkdir(parents=True)
    (fixture_root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    overlay = dataset_root / "variants" / "sample" / "add-line" / "target"
    overlay.mkdir(parents=True)
    (overlay / "module.py").write_text("VALUE = 1\nEXTRA = 2\n", encoding="utf-8")

    manifest = {
        "contract_version": "1.0",
        "fixtures_root": "fixtures",
        "variants_root": "variants",
        "fixtures": [
            {
                "id": "sample",
                "root": "sample",
                "kind": "python",
                "snapshots": [
                    {"id": "snapshot-1", "members": ["module.py"]}
                ],
            }
        ],
        "query_cases_file": "queries.json",
        "change_cases_file": "changes.json",
        "expected_query_count": 1,
        "expected_change_count": 1,
    }
    query_case = {
        "id": "q1",
        "repository_fixture": "sample",
        "snapshot_id": "snapshot-1",
        "question": "Where is VALUE?",
        "intent": "EXACT_SYMBOL",
        "expected_abstention": False,
        "expected_symbols": ["module.VALUE"],
        "expected_relations": [],
        "expected_evidence": [
            {
                "evidence_id": "evidence-1",
                "snapshot_id": "snapshot-1",
                "file_path": "module.py",
                "symbol": "module.VALUE",
                "start_line": 1,
                "end_line": 1,
            }
        ],
        "warnings": [],
        "limitations": [],
        "forbidden_claims": [],
    }
    change_case = {
        "id": "c1",
        "repository_fixture": "sample",
        "snapshot_id": "snapshot-1",
        "base_ref": "HEAD",
        "target_ref": "working-tree:add-line",
        "expected_symbols": ["module.VALUE"],
        "expected_relations": [],
        "expected_evidence": [
            {
                "evidence_id": "evidence-1",
                "snapshot_id": "snapshot-1",
                "file_path": "module.py",
                "symbol": "module.VALUE",
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "expected_changed_symbols": ["module.VALUE"],
        "expected_impact_paths": [],
        "expected_findings": [],
        "warnings": [],
        "limitations": [],
        "forbidden_claims": [],
    }
    (dataset_root / "dataset.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (dataset_root / "queries.json").write_text(
        json.dumps({"contract_version": "1.0", "cases": [query_case]}),
        encoding="utf-8",
    )
    (dataset_root / "changes.json").write_text(
        json.dumps({"contract_version": "1.0", "cases": [change_case]}),
        encoding="utf-8",
    )
    return dataset_root
