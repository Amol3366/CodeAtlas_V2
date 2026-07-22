"""Tests for Windows-safe path handling (Blueprint §4.3.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.domain.errors import RepositoryError, UnsupportedPathError
from codeatlas.repositories import path_security as ps


def test_normalize_root_produces_display_and_key(tmp_path: Path) -> None:
    root = ps.normalize_root(tmp_path)
    assert Path(root.display_path) == tmp_path
    assert root.normalized_path == ps.normalize_key(str(tmp_path.resolve()))
    assert root.path == Path(root.display_path)


def test_normalize_root_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError):
        ps.normalize_root(tmp_path / "does-not-exist")


def test_normalize_root_rejects_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(RepositoryError):
        ps.normalize_root(f)


def test_unc_paths_rejected_without_optin() -> None:
    assert ps.is_unc(r"\\server\share\repo")
    with pytest.raises(UnsupportedPathError):
        ps.normalize_root(r"\\server\share\repo", allow_unc=False)


def test_normalize_key_is_slash_normalized() -> None:
    assert ps.normalize_key("A/B\\C") == ps.normalize_key("A/B/C")


def test_is_within_root(tmp_path: Path) -> None:
    root = str(tmp_path)
    inside = str(tmp_path / "sub" / "file.py")
    outside = str(tmp_path.parent / "other")
    assert ps.is_within_root(root, inside)
    assert ps.is_within_root(root, root)
    assert not ps.is_within_root(root, outside)


def test_read_bytes_reads_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert ps.read_bytes(str(f)) == b"hello"


def test_inspect_child_flags_plain_entry_as_not_reparse(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    info = ps.inspect_child(parent_dir=str(tmp_path), name="sub", real_root=str(tmp_path.resolve()))
    assert info.is_reparse is False
    assert info.escapes_root is False
