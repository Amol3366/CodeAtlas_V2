"""Git state capture through a non-shell argument-array adapter."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codeatlas.repositories.git_state import GitAdapter

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is unavailable"
)


@requires_git
def test_reads_branch_and_head_from_a_real_repository(git_repo: Path) -> None:
    state = GitAdapter().read_state(git_repo)
    assert state.is_repository is True
    assert state.branch == "main"
    assert state.head_commit is not None
    assert len(state.head_commit) == 40
    assert state.is_dirty is False
    assert state.warnings == ()


@requires_git
def test_detects_a_dirty_working_tree(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("# Changed\n", encoding="utf-8")
    assert GitAdapter().read_state(git_repo).is_dirty is True


@requires_git
def test_detects_an_untracked_file_as_dirty(git_repo: Path) -> None:
    (git_repo / "new_file.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert GitAdapter().read_state(git_repo).is_dirty is True


@requires_git
def test_repository_without_commits_reports_no_head(sample_repo: Path) -> None:
    subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=sample_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    state = GitAdapter().read_state(sample_repo)
    assert state.is_repository is True
    assert state.head_commit is None
    assert "GIT_NO_COMMITS" in state.warnings


def test_non_git_directory_is_reported_without_error(sample_repo: Path) -> None:
    # The pytest base temp directory lives inside the CodeAtlas repository, so
    # this also covers a directory nested inside someone else's work tree: Git
    # facts must not be inherited from the enclosing repository.
    state = GitAdapter().read_state(sample_repo)
    assert state.is_repository is False
    assert state.head_commit is None
    assert state.branch is None
    assert state.is_dirty is False
    assert set(state.warnings) & {"GIT_NOT_A_REPOSITORY", "GIT_ROOT_MISMATCH"}


@requires_git
def test_directory_nested_in_another_repository_does_not_inherit_its_state(
    git_repo: Path,
) -> None:
    nested = git_repo / "src" / "payments"
    state = GitAdapter().read_state(nested)
    assert state.is_repository is False
    assert state.head_commit is None
    assert "GIT_ROOT_MISMATCH" in state.warnings


def test_missing_git_executable_degrades(sample_repo: Path) -> None:
    state = GitAdapter(git_executable="git-does-not-exist").read_state(sample_repo)
    assert state.is_repository is False
    assert "GIT_EXECUTABLE_UNAVAILABLE" in state.warnings


@requires_git
def test_timeout_degrades_without_raising(git_repo: Path) -> None:
    state = GitAdapter(timeout_seconds=0.0).read_state(git_repo)
    assert state.is_repository is False
    assert "GIT_TIMEOUT" in state.warnings


def test_adapter_never_uses_a_shell() -> None:
    from codeatlas.repositories import git_state

    source = Path(git_state.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "shell=False" in source


@pytest.mark.parametrize("hostile_name", ["--upload-pack=calc.exe", "-c core.pager=x"])
def test_hostile_directory_names_are_not_treated_as_arguments(
    tmp_path: Path, hostile_name: str
) -> None:
    # A repository root that looks like a Git option must never be parsed as one.
    # The adapter runs Git with cwd set and no path argument, so this degrades to
    # an unusable-Git result rather than executing an injected option.
    root = tmp_path / hostile_name.replace("=", "_").replace(" ", "_")
    root.mkdir()
    state = GitAdapter().read_state(root)
    assert state.is_repository is False
    assert state.head_commit is None
