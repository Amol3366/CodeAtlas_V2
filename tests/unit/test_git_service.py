"""Tests for Git state detection and rename-aware diffs (Blueprint §3.10)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codeatlas.repositories.git_service import GitService

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init")


def test_non_git_directory(tmp_path: Path) -> None:
    state = GitService().get_state(str(tmp_path))
    assert state.is_git_repository is False
    assert state.commit_sha is None
    assert state.branch is None


def test_git_state_after_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")

    state = GitService().get_state(str(tmp_path))
    assert state.is_git_repository is True
    assert state.commit_sha is not None
    assert state.branch is not None
    assert state.is_dirty is False


def test_git_state_detects_dirty_working_tree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "untracked.py").write_text("y = 2\n", encoding="utf-8")

    assert GitService().get_state(str(tmp_path)).is_dirty is True


def test_diff_name_status_detects_rename(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "old.py").write_text("RENAME CONTENT STAYS THE SAME\n" * 5, encoding="utf-8")
    _git(tmp_path, "add", "old.py")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    _git(tmp_path, "mv", "old.py", "new.py")
    _git(tmp_path, "commit", "-m", "rename")
    head = _git(tmp_path, "rev-parse", "HEAD")

    changes = GitService().diff_name_status(str(tmp_path), base, head)
    renames = [c for c in changes if c.status == "R"]
    assert len(renames) == 1
    assert renames[0].old_path == "old.py"
    assert renames[0].path == "new.py"


def test_diff_name_status_on_non_git_is_empty(tmp_path: Path) -> None:
    assert GitService().diff_name_status(str(tmp_path), "HEAD") == []
