"""Deterministic, bounded, non-executing repository scanning."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.errors import ScanLimitExceededError
from codeatlas.domain.paths import canonicalize_root
from codeatlas.domain.repository import ScanLimits
from codeatlas.repositories.ignore_rules import IgnoreRules
from codeatlas.repositories.scanner import RepositoryScanner


def _scan(root_path: Path, limits: ScanLimits | None = None):  # type: ignore[no-untyped-def]
    root = canonicalize_root(str(root_path))
    scanner = RepositoryScanner(limits) if limits else RepositoryScanner()
    return scanner.scan(root, IgnoreRules.load(root))


def test_scan_is_deterministic_and_hashes_content(sample_repo: Path) -> None:
    first = _scan(sample_repo)
    second = _scan(sample_repo)
    paths = [f.relative_path for f in first.files]
    assert paths == sorted(paths)
    assert paths == [
        "README.md",
        "src/payments/idempotency.py",
        "src/payments/service.py",
    ]
    assert first.working_tree_fingerprint == second.working_tree_fingerprint
    assert all(len(f.content_hash) == 64 for f in first.files)


def test_fingerprint_changes_when_content_changes(sample_repo: Path) -> None:
    before = _scan(sample_repo).working_tree_fingerprint
    (sample_repo / "README.md").write_text("# Changed\n", encoding="utf-8")
    assert _scan(sample_repo).working_tree_fingerprint != before


def test_line_counts_include_a_trailing_partial_line(sample_repo: Path) -> None:
    (sample_repo / "partial.md").write_text("one\ntwo", encoding="utf-8")
    result = _scan(sample_repo)
    partial = next(f for f in result.files if f.relative_path == "partial.md")
    assert partial.line_count == 2


def test_scan_skips_oversized_and_binary_files(sample_repo: Path) -> None:
    (sample_repo / "big.py").write_bytes(b"x" * 3_000_000)
    (sample_repo / "blob.py").write_bytes(b"ok\x00binary")
    result = _scan(sample_repo)
    reasons = {s.relative_path: s.reason_code for s in result.skipped}
    assert reasons["big.py"] == "TOO_LARGE"
    assert reasons["blob.py"] == "BINARY"
    assert "big.py" not in [f.relative_path for f in result.files]


def test_scan_skips_ignored_entries_with_a_reason(sample_repo: Path) -> None:
    (sample_repo / "__pycache__").mkdir()
    (sample_repo / "__pycache__" / "cached.py").write_text("x\n", encoding="utf-8")
    result = _scan(sample_repo)
    assert any(
        s.relative_path == "__pycache__" and s.reason_code == "IGNORED"
        for s in result.skipped
    )
    assert all("__pycache__" not in f.relative_path for f in result.files)


def test_scan_respects_the_depth_limit(sample_repo: Path) -> None:
    deep = sample_repo / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x = 1\n", encoding="utf-8")
    result = _scan(sample_repo, ScanLimits(max_depth=2))
    assert all(f.relative_path != "a/b/c/deep.py" for f in result.files)
    assert any(s.reason_code == "TOO_DEEP" for s in result.skipped)


def test_scan_raises_when_file_limit_exceeded(sample_repo: Path) -> None:
    with pytest.raises(ScanLimitExceededError):
        _scan(sample_repo, ScanLimits(max_files=1))


def test_scan_skips_paths_longer_than_the_limit(sample_repo: Path) -> None:
    (sample_repo / "long_name_file.py").write_text("x = 1\n", encoding="utf-8")
    result = _scan(sample_repo, ScanLimits(max_relative_path_length=12))
    assert any(s.reason_code == "PATH_REJECTED" for s in result.skipped)


def test_scan_does_not_execute_repository_code(sample_repo: Path) -> None:
    marker = sample_repo / "executed.txt"
    (sample_repo / "sitecustomize.py").write_text(
        f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8"
    )
    _scan(sample_repo)
    assert marker.exists() is False


def test_scan_excludes_a_link_that_escapes_the_root(sample_repo: Path) -> None:
    outside = sample_repo.parent / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    link = sample_repo / "linked"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(outside, link, target_is_directory=True)

    result = _scan(sample_repo)
    assert all("linked" not in f.relative_path for f in result.files)
    assert any(s.reason_code == "OUTSIDE_ROOT" for s in result.skipped)
    assert any("SECURITY_LINK_ESCAPE" in warning for warning in result.warnings)
