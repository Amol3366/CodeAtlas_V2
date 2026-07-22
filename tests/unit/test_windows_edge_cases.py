"""Windows edge-case scanner tests: casing preservation and long paths.

Exit criteria (CLAUDE.md Phase 1): "Windows edge cases tested: casing
conflicts, long paths, locked files, junctions." Locked files are covered in
test_scanner.py (unreadable diagnostic) and junctions in test_scanner_symlinks.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeatlas.repositories import path_security as ps
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.settings.config import ScanConfig, default_language_index


def _scan(root: Path) -> object:
    scanner = RepositoryScanner(ScanConfig(), default_language_index())
    return scanner.scan(ps.normalize_root(root))


def test_display_path_preserves_casing_normalized_key_folds(tmp_path: Path) -> None:
    (tmp_path / "MyModule.py").write_text("x = 1\n", encoding="utf-8")
    result = _scan(tmp_path)
    entry = next(e for e in result.manifest.entries)  # type: ignore[attr-defined]
    assert entry.display_path == "MyModule.py"
    expected_key = "mymodule.py" if ps.IS_WINDOWS else "MyModule.py"
    assert entry.normalized_path == expected_key


def test_long_path_is_scanned(tmp_path: Path) -> None:
    deep = tmp_path
    segment = "d" * 40
    while len(str(deep)) < 300:
        deep = deep / segment
    try:
        os.makedirs(deep, exist_ok=True)
        (deep / "leaf.py").write_text("value = 1\n", encoding="utf-8")
    except OSError as exc:
        pytest.skip(f"long paths unavailable in this environment: {exc}")

    result = _scan(tmp_path)
    assert any(
        e.display_path.endswith("leaf.py")
        for e in result.manifest.entries  # type: ignore[attr-defined]
    )
