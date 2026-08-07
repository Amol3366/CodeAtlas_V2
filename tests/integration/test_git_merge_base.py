"""The merge-base lookup that `--since` is built on."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.errors import GitRefUnresolvableError
from codeatlas.repositories.git_diff import GitDiffAdapter

_IDENTITY = ("-c", "user.email=dev@example.invalid", "-c", "user.name=Dev")


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _rev_parse(root: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write(root: Path, name: str, body: str) -> None:
    (root / name).write_text(body, encoding="utf-8")
    _git(root, *_IDENTITY, "add", ".")
    _git(root, *_IDENTITY, "commit", "-m", name)


def test_merge_base_is_where_the_branch_diverged(tmp_path: Path) -> None:
    """The case that makes this method necessary.

    A two-dot diff against a trunk that has moved reports the trunk's own new
    commits as changes to your branch, inverted. Only a merge base answers
    "what did I change".
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    _write(root, "a.py", "a = 1\n")
    divergence = _rev_parse(root, "HEAD")

    _git(root, "checkout", "-b", "feature")
    _write(root, "b.py", "b = 1\n")

    _git(root, "checkout", "main")
    _write(root, "c.py", "c = 1\n")
    _git(root, "checkout", "feature")

    resolved = GitDiffAdapter().merge_base(root, "main")

    assert resolved == divergence
    # And it is not simply the trunk tip, which is what a two-dot diff would
    # have compared against.
    assert resolved != _rev_parse(root, "main")


def test_an_unresolvable_ref_raises(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    _write(root, "a.py", "a = 1\n")

    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().merge_base(root, "no-such-branch")


def test_a_hostile_ref_is_refused_before_reaching_git(tmp_path: Path) -> None:
    # `_validate_ref` rejects a leading dash so a ref can never arrive in the
    # argument array as a flag.
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    _write(root, "a.py", "a = 1\n")

    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().merge_base(root, "--upload-pack=evil")
