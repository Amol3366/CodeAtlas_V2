"""Exact symbol resolution on Python fixtures (Blueprint §13.5, Phase 3 exit ≥ 98%).

For every benchmark ``required_evidence`` entry that points at a ``.py`` file, the
parser must produce a symbol whose qualified name matches. Measured against the
hand-authored ground truth, not LLM output.
"""

from __future__ import annotations

import json
from pathlib import Path

from codeatlas.domain.enums import Language
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.python.parser import PythonParser

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "tests" / "evaluation"


def _python_targets() -> list[tuple[Path, str]]:
    data = json.loads((EVAL_DIR / "benchmark_questions.json").read_text(encoding="utf-8"))
    fixtures: dict[str, str] = data["fixtures"]
    targets: list[tuple[Path, str]] = []
    for question in data["questions"]:
        root = REPO_ROOT / fixtures[question["repository_fixture"]]
        for evidence in question["required_evidence"]:
            file_path = evidence["file_path"]
            if file_path.endswith(".py"):
                targets.append((root / file_path, evidence["symbol"]))
    return targets


def _qualified_names(path: Path, repo_root: Path) -> set[str]:
    rel = path.relative_to(repo_root).as_posix()
    result = PythonParser().parse(ParseRequest("repo_x", rel, Language.PYTHON, path.read_bytes()))
    return {s.qualified_name for s in result.symbols}


def test_exact_symbol_resolution_at_least_98_percent() -> None:
    targets = _python_targets()
    assert targets, "expected Python benchmark targets"

    resolved = 0
    misses: list[str] = []
    # Cache parsed files.
    cache: dict[Path, set[str]] = {}
    for path, symbol in targets:
        repo_root = _repo_root_for(path)
        names = cache.setdefault(path, _qualified_names(path, repo_root))
        if symbol in names:
            resolved += 1
        else:
            misses.append(f"{path.name}::{symbol}")

    rate = resolved / len(targets)
    assert rate >= 0.98, f"resolution {rate:.3f} < 0.98; misses={misses}"


def _repo_root_for(path: Path) -> Path:
    # Fixture roots live directly under tests/fixtures/<name>/.
    for parent in path.parents:
        if parent.parent.name == "fixtures":
            return parent
    raise AssertionError(f"could not locate fixture root for {path}")
