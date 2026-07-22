"""Junction/symlink safety tests (Blueprint §4.3.2). Skipped when unprivileged."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeatlas.repositories import path_security as ps
from codeatlas.repositories.scanner import RepositoryScanner, SkipReason
from codeatlas.settings.config import ScanConfig, default_language_index


def _make_symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:  # Windows without privilege / dev mode
        pytest.skip(f"symlinks unavailable in this environment: {exc}")


def test_symlink_escaping_root_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _make_symlink(repo / "escape", outside)

    scanner = RepositoryScanner(ScanConfig(), default_language_index())
    result = scanner.scan(ps.normalize_root(repo))

    paths = {entry.display_path for entry in result.manifest.entries}
    assert "app.py" in paths
    assert not any("secret" in p for p in paths)
    assert any(
        s.reason is SkipReason.SYMLINK_ESCAPE and s.display_path == "escape" for s in result.skipped
    )
