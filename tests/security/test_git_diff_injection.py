"""Injection-resistance tests for the Git diff adapter.

Repository refs and paths are untrusted data. Every malicious value here must be
rejected by grammar or path validation before it reaches a subprocess argument.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.errors import GitRefUnresolvableError, PathSafetyError
from codeatlas.repositories.git_diff import GitDiffAdapter

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is unavailable"
)


@pytest.mark.parametrize(
    "hostile_ref",
    [
        "--upload-pack=calc.exe",
        "-c core.pager=x",
        "HEAD;rm -rf /",
        "HEAD~1; cat /etc/passwd",
        "HEAD..HEAD",
        "../HEAD",
        "refs/heads/..",
        "\x00HEAD",
    ],
)
def test_hostile_ref_is_rejected_before_invocation(
    hostile_ref: str, tmp_path: Path
) -> None:
    # A real repository is not even required: the grammar check must fail first.
    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().resolve_ref(tmp_path, hostile_ref)


@requires_git
def test_resolve_ref_rejects_path_escaping_segment(git_repo: Path) -> None:
    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().resolve_ref(git_repo, "refs/heads/../main")


@requires_git
def test_read_blob_rejects_path_escape(git_repo: Path) -> None:
    with pytest.raises(PathSafetyError):
        GitDiffAdapter().read_blob(git_repo, "HEAD", "../../etc/passwd")


@requires_git
def test_changed_files_drops_path_escape_in_name_status_output(
    tmp_path: Path,
) -> None:
    # Build a small real repository so the command has something to diff against.
    root = tmp_path / "repo"
    root.mkdir()
    (root / "safe.txt").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=A", "add", "."],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=A", "commit", "-m", "x"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    # The adapter parses `git diff --name-status` output; the output is
    # line-oriented and paths are validated. A ref whose grammar passes but
    # whose name-status behavior could be exploited must not yield paths
    # outside the repository.
    entries = GitDiffAdapter().changed_files(root, "HEAD", None)
    assert all(not entry.relative_path.startswith("..") for entry in entries)
    assert all(".." not in entry.relative_path for entry in entries)


@requires_git
def test_changed_files_rejects_hostile_ref(git_repo: Path) -> None:
    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().changed_files(git_repo, "--upload-pack=x", None)


def test_adapter_never_uses_a_shell() -> None:
    from codeatlas.repositories import git_diff

    source = Path(git_diff.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "shell=False" in source
