"""Tests for the deterministic repository scanner (Blueprint §4.3, Phase 1)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from codeatlas.domain.enums import FileClassification
from codeatlas.repositories import path_security as ps
from codeatlas.repositories.scanner import (
    RepositoryScanner,
    ScanManifest,
    SkipReason,
    content_hash,
    count_lines,
    diff_manifests,
)
from codeatlas.settings.config import ScanConfig, default_language_index


def _scanner(config: ScanConfig | None = None) -> RepositoryScanner:
    return RepositoryScanner(config or ScanConfig(), default_language_index())


def _scan(root: Path, config: ScanConfig | None = None) -> ScanManifest:
    return _scanner(config).scan(ps.normalize_root(root)).manifest


# --- Content hashing / normalization ---


def test_content_hash_normalizes_line_endings() -> None:
    assert content_hash(b"a\r\nb", is_binary=False) == content_hash(b"a\nb", is_binary=False)
    assert content_hash(b"a\rb", is_binary=False) == content_hash(b"a\nb", is_binary=False)


def test_content_hash_strips_bom() -> None:
    assert content_hash(b"\xef\xbb\xbfabc", is_binary=False) == content_hash(
        b"abc", is_binary=False
    )


def test_binary_content_hash_is_raw() -> None:
    raw = b"\x00\x01\r\n\x02"
    assert content_hash(raw, is_binary=True) != content_hash(raw, is_binary=False)


def test_count_lines() -> None:
    assert count_lines(b"", is_binary=False) == 0
    assert count_lines(b"a\nb\n", is_binary=False) == 2
    assert count_lines(b"a\nb", is_binary=False) == 2
    assert count_lines(b"\x00\x00", is_binary=True) == 0


# --- Determinism (exit criterion: two scans -> byte-identical manifest) ---


@pytest.mark.parametrize(
    "fixture", ["python_repo", "typescript_repo", "markdown_repo", "mixed_repo"]
)
def test_scan_is_byte_identical_across_runs(
    fixture: str, copy_fixture: Callable[[str], Path]
) -> None:
    root = copy_fixture(fixture)
    first = _scan(root).to_json()
    second = _scan(root).to_json()
    assert first == second
    assert first  # non-empty manifest


def test_manifest_entries_sorted_by_normalized_path(copy_fixture: Callable[[str], Path]) -> None:
    manifest = _scan(copy_fixture("python_repo"))
    keys = [entry.normalized_path for entry in manifest.entries]
    assert keys == sorted(keys)


def test_scan_classifies_known_fixture_files(copy_fixture: Callable[[str], Path]) -> None:
    manifest = _scan(copy_fixture("python_repo"))
    by_path = {entry.display_path: entry for entry in manifest.entries}
    payment = by_path["src/services/payment_service.py"]
    assert payment.classification is FileClassification.SOURCE_CODE
    assert by_path["tests/test_auth.py"].classification is FileClassification.TEST_CODE
    assert by_path["README.md"].classification is FileClassification.DOCUMENTATION
    assert by_path["pyproject.toml"].classification is FileClassification.DEPENDENCY_MANIFEST


# --- Ignore + non-exclusion guarantee integration ---


def test_ignored_directories_are_skipped_not_scanned(
    tmp_path: Path, write_tree: Callable[[Path, Mapping[str, str | bytes]], None]
) -> None:
    write_tree(
        tmp_path,
        {
            "src/app.py": "x = 1\n",
            "node_modules/pkg/index.js": "module.exports = 1;\n",
            "__pycache__/app.cpython-312.pyc": b"\x00\x01",
        },
    )
    result = _scanner().scan(ps.normalize_root(tmp_path))
    paths = {entry.display_path for entry in result.manifest.entries}
    assert "src/app.py" in paths
    assert not any("node_modules" in p for p in paths)
    reasons = {(s.display_path, s.reason) for s in result.skipped}
    assert ("node_modules", SkipReason.IGNORED) in reasons


def test_non_exclusion_guarantee(
    tmp_path: Path, write_tree: Callable[[Path, Mapping[str, str | bytes]], None]
) -> None:
    write_tree(
        tmp_path,
        {
            ".gitignore": "*.sql\n*.lock\nDockerfile\n",
            "db/schema.sql": "SELECT 1;\n",
            "uv.lock": "# lock\n",
            "Dockerfile": "FROM scratch\n",
        },
    )
    manifest = _scan(tmp_path)
    paths = {entry.display_path for entry in manifest.entries}
    assert {"db/schema.sql", "uv.lock", "Dockerfile"} <= paths


# --- Diagnostics: unreadable + too large (no crashes) ---


def test_too_large_file_skipped_with_reason(
    tmp_path: Path, write_tree: Callable[[Path, Mapping[str, str | bytes]], None]
) -> None:
    write_tree(tmp_path, {"big.py": "x" * 5000, "small.py": "y = 1\n"})
    config = ScanConfig(max_file_size_bytes=1000)
    result = _scanner(config).scan(ps.normalize_root(tmp_path))
    paths = {entry.display_path for entry in result.manifest.entries}
    assert "small.py" in paths
    assert "big.py" not in paths
    assert any(s.reason is SkipReason.TOO_LARGE for s in result.skipped)


def test_unreadable_file_produces_diagnostic_not_crash(
    tmp_path: Path,
    write_tree: Callable[[Path, Mapping[str, str | bytes]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_tree(tmp_path, {"ok.py": "a = 1\n", "locked.py": "b = 2\n"})
    real_read = ps.read_bytes

    def fake_read(path: str, *, long_paths_enabled: bool = True) -> bytes:
        if path.endswith("locked.py"):
            raise PermissionError("locked")
        return real_read(path, long_paths_enabled=long_paths_enabled)

    monkeypatch.setattr("codeatlas.repositories.scanner.ps.read_bytes", fake_read)
    result = _scanner().scan(ps.normalize_root(tmp_path))
    paths = {entry.display_path for entry in result.manifest.entries}
    assert "ok.py" in paths
    assert "locked.py" not in paths
    assert any(
        s.reason is SkipReason.UNREADABLE and s.display_path == "locked.py" for s in result.skipped
    )


# --- Change detection between scans ---


def test_diff_detects_added_modified_deleted_renamed(
    tmp_path: Path, write_tree: Callable[[Path, Mapping[str, str | bytes]], None]
) -> None:
    write_tree(
        tmp_path,
        {
            "keep.py": "unchanged\n",
            "change.py": "before\n",
            "gone.py": "delete me\n",
            "old_name.py": "RENAME_UNIQUE_CONTENT_123\n",
        },
    )
    before = _scan(tmp_path)

    (tmp_path / "change.py").write_text("after\n", encoding="utf-8")
    (tmp_path / "gone.py").unlink()
    (tmp_path / "old_name.py").unlink()
    (tmp_path / "new_name.py").write_text("RENAME_UNIQUE_CONTENT_123\n", encoding="utf-8")
    (tmp_path / "added.py").write_text("brand new\n", encoding="utf-8")

    after = _scan(tmp_path)
    diff = diff_manifests(before, after)

    assert diff.added == ("added.py",)
    assert diff.modified == ("change.py",)
    assert diff.deleted == ("gone.py",)
    assert diff.renamed == (("old_name.py", "new_name.py"),)


def test_diff_of_identical_manifests_is_empty(copy_fixture: Callable[[str], Path]) -> None:
    root = copy_fixture("python_repo")
    diff = diff_manifests(_scan(root), _scan(root))
    assert diff == diff_manifests(_scan(root), _scan(root))
    assert not diff.added and not diff.modified and not diff.deleted and not diff.renamed
