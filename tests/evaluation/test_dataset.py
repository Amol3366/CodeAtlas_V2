from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import DatasetError, load_dataset

DATASET_ROOT = Path("tests/evaluation/cases")


def test_shipped_dataset_has_declared_phase_zero_cardinality() -> None:
    dataset = load_dataset(DATASET_ROOT)

    assert len(dataset.fixtures) == 6
    assert len(dataset.query_cases) == 40
    assert len(dataset.change_cases) == 25
    assert len({case.id for case in dataset.query_cases}) == 40
    assert len({case.id for case in dataset.change_cases}) == 25


def test_shipped_dataset_evidence_resolves_inside_fixture_roots() -> None:
    dataset = load_dataset(DATASET_ROOT)

    query_evidence = [
        item
        for case in dataset.query_cases
        for item in case.expected_evidence
    ]
    change_evidence = [
        item
        for case in dataset.change_cases
        for item in case.expected_evidence
    ]
    evidence = [*query_evidence, *change_evidence]
    assert evidence
    for item in evidence:
        assert item.validated_line_count >= item.end_line


def test_dataset_rejects_path_traversal(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    query_path = dataset_root / "queries.json"
    payload = json.loads(query_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_evidence"][0]["file_path"] = "../outside.py"
    query_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="repository-relative"):
        load_dataset(dataset_root)


def test_dataset_rejects_evidence_beyond_end_of_file(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    query_path = dataset_root / "queries.json"
    payload = json.loads(query_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_evidence"][0]["end_line"] = 20
    query_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="line range"):
        load_dataset(dataset_root)


def test_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    query_path = dataset_root / "queries.json"
    payload = json.loads(query_path.read_text(encoding="utf-8"))
    payload["cases"].append(payload["cases"][0])
    query_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="unique"):
        load_dataset(dataset_root)


def test_dataset_rejects_malformed_manifest(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    (dataset_root / "dataset.json").write_text("{", encoding="utf-8")

    with pytest.raises(DatasetError):
        load_dataset(dataset_root)


def test_dataset_rejects_manifest_symlink_escape(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "queries.json").write_text(
        (dataset_root / "queries.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    link = dataset_root / "linked"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(outside, link, target_is_directory=True)
    manifest_path = dataset_root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["query_cases_file"] = "linked/queries.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetError, match="repository-relative"):
        load_dataset(dataset_root)


def test_dataset_rejects_cross_snapshot_evidence(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    query_path = dataset_root / "queries.json"
    payload = json.loads(query_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_evidence"][0]["snapshot_id"] = "snapshot-2"
    query_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="snapshot membership"):
        load_dataset(dataset_root)


def test_loading_fixture_never_executes_repository_code(tmp_path: Path) -> None:
    dataset_root = _minimal_dataset(tmp_path)
    fixture_root = dataset_root / "fixtures" / "sample"
    marker = tmp_path / "executed.txt"
    (fixture_root / "module.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    load_dataset(dataset_root)

    assert not marker.exists()


def _minimal_dataset(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "cases"
    dataset_root.mkdir()
    fixtures_root = dataset_root / "fixtures"
    fixture_root = fixtures_root / "sample"
    fixture_root.mkdir(parents=True)
    (fixture_root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    manifest = {
        "contract_version": "1.0",
        "fixtures_root": "fixtures",
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
    shared = {
        "id": "case-1",
        "repository_fixture": "sample",
        "snapshot_id": "snapshot-1",
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
        "forbidden_claims": ["The fixture was executed."],
    }
    query_case = {
        **shared,
        "question": "Where is VALUE defined?",
        "intent": "EXACT_SYMBOL",
        "expected_abstention": False,
    }
    change_case = {
        **shared,
        "base_ref": "base",
        "target_ref": "target",
        "expected_changed_symbols": ["module.VALUE"],
        "expected_impact_paths": [],
        "expected_findings": [],
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


# --- Working-tree integrity ----------------------------------------------------

_CORPUS_ROOTS = (
    Path("tests/evaluation/cases"),
    Path("tests/evaluation/semantic_cases"),
    Path("tests/evaluation/invariant_cases"),
)


@pytest.mark.parametrize("root", _CORPUS_ROOTS, ids=lambda item: item.name)
def test_every_corpus_file_has_lf_endings_in_the_working_tree(root: Path) -> None:
    """Git normalises on read, so it cannot show you this drift.

    `.gitattributes` declares `* text=auto eol=lf` precisely because the change
    engine hashes bytes and diffs lines: a corpus file rewritten with CRLF makes
    every line of it differ, so every symbol in it reports as changed. Because
    `text=auto` normalises the working tree back to LF when comparing,
    `git status` stays clean while the bytes the evaluation actually reads have
    drifted — and a baseline measured against that drift will not reproduce on a
    fresh clone.

    That is not hypothetical. `baseline-phase-7`'s `changed_symbol_precision` was
    0.2000 for exactly this reason: one variant file held CRLF, so all five
    functions in it were reported changed against a corpus declaring one. The
    correct value is 1.0000.
    """
    offenders = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        if b"\r\n" in data:
            offenders.append(str(path))

    assert offenders == [], (
        "CRLF found in corpus files; the evaluation reads these bytes directly. "
        "Restore them with `git checkout -- <path>` so .gitattributes applies."
    )
