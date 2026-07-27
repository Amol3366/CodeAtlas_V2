"""Git diff operations through a non-shell argument-array adapter."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.errors import GitRefUnresolvableError
from codeatlas.repositories.git_diff import GitDiffAdapter

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is unavailable"
)


@requires_git
def test_resolve_ref_returns_full_sha_for_head(git_repo: Path) -> None:
    adapter = GitDiffAdapter()
    resolved = adapter.resolve_ref(git_repo, "HEAD")
    assert len(resolved) == 40
    assert all(character in "0123456789abcdef" for character in resolved)


@requires_git
def test_resolve_ref_returns_full_sha_for_head_tilde(
    git_repo_with_history: Path,
) -> None:
    adapter = GitDiffAdapter()
    assert len(adapter.resolve_ref(git_repo_with_history, "HEAD~1")) == 40


@requires_git
def test_resolve_ref_returns_unchanged_full_sha(git_repo: Path) -> None:
    adapter = GitDiffAdapter()
    full = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert adapter.resolve_ref(git_repo, full) == full


@requires_git
def test_resolve_ref_raises_for_unresolvable_ref(git_repo: Path) -> None:
    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().resolve_ref(git_repo, "HEAD~99")


@requires_git
def test_changed_files_detects_dirty_working_tree_modification(
    git_repo_with_history: Path,
) -> None:
    (git_repo_with_history / "README.md").write_text("# Dirty\n", encoding="utf-8")
    entries = GitDiffAdapter().changed_files(git_repo_with_history, "HEAD", None)

    assert len(entries) == 1
    assert entries[0].relative_path == "README.md"
    assert entries[0].change_kind == "modified"
    assert entries[0].base_path is None
    assert entries[0].base_content_hash != entries[0].target_content_hash


@requires_git
def test_changed_files_reports_rename_modify_add_delete(
    git_repo_with_history: Path,
) -> None:
    entries = GitDiffAdapter().changed_files(
        git_repo_with_history, "HEAD~1", "HEAD"
    )
    by_path = {entry.relative_path: entry for entry in entries}

    if len(entries) != 4:
        for entry in entries:
            print(entry)  # debugging unexpected results
    assert len(entries) == 4

    assert "src/payments/service_renamed.py" in by_path
    renamed = by_path["src/payments/service_renamed.py"]
    assert renamed.change_kind == "renamed"
    assert renamed.base_path == "src/payments/service.py"
    assert renamed.base_content_hash == renamed.target_content_hash

    assert "src/payments/new_file.py" in by_path
    assert by_path["src/payments/new_file.py"].change_kind == "added"

    deleted = [entry for entry in entries if entry.change_kind == "deleted"]
    assert len(deleted) == 1
    assert deleted[0].relative_path == "src/payments/idempotency.py"
    assert deleted[0].base_content_hash != ""

    assert "README.md" in by_path
    modified = by_path["README.md"]
    assert modified.change_kind == "modified"
    assert modified.base_content_hash != modified.target_content_hash


@requires_git
def test_changed_files_edited_rename_is_delete_plus_add(
    git_repo_with_edited_rename: Path,
) -> None:
    entries = GitDiffAdapter().changed_files(
        git_repo_with_edited_rename, "HEAD~1", "HEAD"
    )
    kinds = {entry.relative_path: entry.change_kind for entry in entries}

    assert kinds.get("src/payments/service_renamed.py") == "added"
    assert kinds.get("src/payments/service.py") == "deleted"
    assert "renamed" not in kinds.values()


@requires_git
def test_changed_files_handles_unchanged_commit_range(git_repo: Path) -> None:
    entries = GitDiffAdapter().changed_files(git_repo, "HEAD", "HEAD")
    assert entries == ()


@requires_git
def test_read_blob_returns_commit_contents(git_repo_with_history: Path) -> None:
    adapter = GitDiffAdapter()
    current = adapter.read_blob(git_repo_with_history, "HEAD", "README.md")
    previous = adapter.read_blob(git_repo_with_history, "HEAD~1", "README.md")

    assert current is not None
    assert previous is not None
    assert current.decode("utf-8") == "# Renamed\n"
    assert previous.decode("utf-8") == "# Sample\n"


@requires_git
def test_read_blob_returns_none_for_missing_path(git_repo: Path) -> None:
    assert GitDiffAdapter().read_blob(git_repo, "HEAD", "does/not/exist.py") is None


@requires_git
def test_list_files_returns_contract_valid_paths(git_repo: Path) -> None:
    paths = GitDiffAdapter().list_files(git_repo, "HEAD")
    assert "src/payments/service.py" in paths
    assert all(not path.startswith("/") for path in paths)
    assert all("\\" not in path for path in paths)


@requires_git
def test_changed_files_output_is_deterministically_ordered(
    git_repo_with_history: Path,
) -> None:
    first = GitDiffAdapter().changed_files(git_repo_with_history, "HEAD~1", "HEAD")
    second = GitDiffAdapter().changed_files(git_repo_with_history, "HEAD~1", "HEAD")
    assert first == second


def test_archive_returns_the_same_bytes_as_per_blob_reads(
    git_repo_with_history: Path,
) -> None:
    """`archive` is a performance path, never a different truth: every file it
    returns is byte-identical to what `read_blob` reads."""
    adapter = GitDiffAdapter()
    head = adapter.resolve_ref(git_repo_with_history, "HEAD")

    contents = adapter.archive(git_repo_with_history, head)

    assert contents is not None
    assert set(contents) == set(adapter.list_files(git_repo_with_history, head))
    for path, blob in contents.items():
        assert blob == adapter.read_blob(git_repo_with_history, head, path)
