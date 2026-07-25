"""Canonicalization and containment rules for approved repository roots."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.errors import PathOutsideRootError, PathSafetyError
from codeatlas.domain.paths import (
    canonicalize_root,
    is_inside_root,
    normalize_relative_path,
    resolve_inside_root,
)


def test_canonicalize_root_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        canonicalize_root(str(tmp_path / "missing"))


def test_canonicalize_root_rejects_file(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(PathSafetyError):
        canonicalize_root(str(target))


def test_canonicalize_root_rejects_empty_input() -> None:
    with pytest.raises(PathSafetyError):
        canonicalize_root("   ")


def test_canonicalize_root_returns_an_absolute_resolved_directory(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "repo" / "inner"
    nested.mkdir(parents=True)
    root = canonicalize_root(str(tmp_path / "repo" / "." / "inner"))
    assert root.is_absolute()
    assert root == nested.resolve()


@pytest.mark.skipif(os.name != "nt", reason="UNC paths are Windows-specific")
def test_canonicalize_root_rejects_unc_paths() -> None:
    with pytest.raises(PathSafetyError):
        canonicalize_root(r"\\server\share\repo")


def test_normalize_relative_path_returns_posix_relative_path(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    target = tmp_path / "src" / "payments" / "service.py"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert normalize_relative_path(root, target) == "src/payments/service.py"


def test_normalize_relative_path_rejects_traversal(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    with pytest.raises(PathSafetyError):
        normalize_relative_path(root, root.parent / "outside.py")


def test_normalize_relative_path_rejects_the_root_itself(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    with pytest.raises(PathSafetyError):
        normalize_relative_path(root, root)


@pytest.mark.skipif(os.name != "nt", reason="Windows reserved device names")
def test_normalize_relative_path_rejects_reserved_device_names(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    with pytest.raises(PathSafetyError):
        normalize_relative_path(root, root / "NUL.py")


def test_resolve_inside_root_rejects_backslash_and_absolute_input(
    tmp_path: Path,
) -> None:
    root = canonicalize_root(str(tmp_path))
    for candidate in ("..\\outside.py", "C:/Windows/System32/cmd.exe", "a/../../b.py"):
        with pytest.raises((PathSafetyError, PathOutsideRootError)):
            resolve_inside_root(root, candidate)


def test_resolve_inside_root_returns_the_contained_path(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x", encoding="utf-8")
    assert resolve_inside_root(root, "src/a.py") == (root / "src" / "a.py")


def test_is_inside_root_accepts_the_root_and_descendants(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    nested = root / "src" / "deep"
    nested.mkdir(parents=True)
    assert is_inside_root(root, root) is True
    assert is_inside_root(root, nested) is True
    assert is_inside_root(root, root.parent) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive comparison")
def test_is_inside_root_is_case_insensitive_on_windows(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    (root / "src").mkdir()
    assert is_inside_root(root, Path(str(root / "src").upper())) is True


def test_junction_or_symlink_escape_is_not_inside_root(tmp_path: Path) -> None:
    root_path = tmp_path / "repo"
    root_path.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    link = root_path / "linked"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(outside, link, target_is_directory=True)
    root = canonicalize_root(str(root_path))
    assert is_inside_root(root, link / "secret.py") is False
