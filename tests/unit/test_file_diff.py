"""Unit tests for file-level diff and directory-backed state views."""

from __future__ import annotations

from pathlib import Path

from codeatlas.analysis.file_diff import compute_file_changes
from codeatlas.analysis.states import DirectoryStateView
from codeatlas.contracts import FileChangeKind
from codeatlas.domain.change import FileChange


def _directory_view(root: Path) -> DirectoryStateView:
    return DirectoryStateView(root)


def test_unchanged_directories_produce_no_changes(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
        (directory / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert changes == ()


def test_added_file_detected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (target / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (target / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert changes == (
        FileChange(
            path="src/b.py",
            kind=FileChangeKind.ADDED,
            content_hash_changed=True,
        ),
    )


def test_deleted_file_detected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (base / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (target / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert changes == (
        FileChange(
            path="src/b.py",
            kind=FileChangeKind.DELETED,
            content_hash_changed=True,
        ),
    )


def test_modified_file_detected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (target / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert changes == (
        FileChange(
            path="src/a.py",
            kind=FileChangeKind.MODIFIED,
            content_hash_changed=True,
        ),
    )


def test_rename_by_hash(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "old.py").write_text("x = 1\n", encoding="utf-8")
    (target / "src" / "new.py").write_text("x = 1\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert changes == (
        FileChange(
            path="src/new.py",
            kind=FileChangeKind.RENAMED,
            base_path="src/old.py",
            content_hash_changed=False,
        ),
    )


def test_edited_rename_is_delete_plus_add(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "old.py").write_text("x = 1\n", encoding="utf-8")
    (target / "src" / "new.py").write_text("x = 2\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert {change.path for change in changes} == {"src/old.py", "src/new.py"}
    assert all(
        change.kind in {FileChangeKind.DELETED, FileChangeKind.ADDED}
        for change in changes
    )
    assert FileChangeKind.RENAMED not in {change.kind for change in changes}


def test_multiple_renames_pair_deterministically(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "a.py").write_text("A\n", encoding="utf-8")
    (base / "src" / "b.py").write_text("B\n", encoding="utf-8")
    (target / "src" / "x.py").write_text("A\n", encoding="utf-8")
    (target / "src" / "y.py").write_text("B\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    assert len(changes) == 2
    assert all(change.kind == FileChangeKind.RENAMED for change in changes)
    paths = {change.path for change in changes}
    base_paths = {change.base_path for change in changes}
    assert paths == {"src/x.py", "src/y.py"}
    assert base_paths == {"src/a.py", "src/b.py"}


def test_ambiguous_rename_falls_back_to_delete_add(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "a.py").write_text("same\n", encoding="utf-8")
    (base / "src" / "b.py").write_text("same\n", encoding="utf-8")
    (target / "src" / "x.py").write_text("same\n", encoding="utf-8")
    (target / "src" / "y.py").write_text("same\n", encoding="utf-8")

    changes = compute_file_changes(_directory_view(base), _directory_view(target))
    kinds = {change.kind for change in changes}
    assert FileChangeKind.RENAMED not in kinds
    assert kinds == {FileChangeKind.DELETED, FileChangeKind.ADDED}


def test_changes_are_deterministically_ordered(tmp_path: Path) -> None:
    base = tmp_path / "base"
    target = tmp_path / "target"
    for directory in (base, target):
        (directory / "src").mkdir(parents=True)
    (base / "src" / "z.py").write_text("z\n", encoding="utf-8")
    (base / "src" / "a.py").write_text("a\n", encoding="utf-8")
    (target / "src" / "m.py").write_text("m\n", encoding="utf-8")

    first = compute_file_changes(_directory_view(base), _directory_view(target))
    second = compute_file_changes(_directory_view(base), _directory_view(target))
    assert first == second
    assert [change.path for change in first] == ["src/a.py", "src/m.py", "src/z.py"]


def test_directory_state_view_honors_ignore_rules(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "__pycache__" / "a.pyc").write_bytes(b"\x00")

    view = DirectoryStateView(root)
    paths = {file.relative_path for file in view.list_files()}
    assert paths == {"src/a.py"}


def test_directory_state_view_read_verifies_hash(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    view = DirectoryStateView(root)
    assert view.read_file("src/a.py") is not None

    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert view.read_file("src/a.py") is None


def test_directory_state_view_read_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    view = DirectoryStateView(root)
    assert view.read_file("../a.py") is None


def test_directory_state_view_read_returns_none_for_missing_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)

    view = DirectoryStateView(root)
    assert view.read_file("src/missing.py") is None


def test_directory_state_view_respects_scan_limits(tmp_path: Path) -> None:
    from codeatlas.domain.repository import ScanLimits

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "large.py").write_text("x\n" * 100)

    view = DirectoryStateView(root, limits=ScanLimits(max_file_bytes=10))
    assert view.list_files() == ()
