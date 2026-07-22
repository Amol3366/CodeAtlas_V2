r"""Windows-safe path handling and security (Blueprint §4.3.2, CLAUDE.md §2.13).

Responsibilities:
- normalize a repository root: absolute, casing-preserving display path plus a
  normalized comparison key, with a junction/symlink-resolved ``real_path``;
- reject UNC paths unless explicitly allowed;
- reject non-existent / unreadable roots and path traversal that escapes the root;
- detect reparse points (symlinks *and* Windows junctions) and tell whether a
  target escapes the repository root;
- read file bytes with long-path (``\\?\``) support on Windows.

All comparisons use ``os.path.normcase`` so casing differences on Windows never
cause a path to be treated as outside the root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from codeatlas.domain.errors import PathSecurityError, RepositoryError, UnsupportedPathError

IS_WINDOWS = os.name == "nt"
_LONG_PATH_THRESHOLD = 255


def normalize_key(path: str) -> str:
    """Return the case/slash-normalized comparison key for a path string."""
    unified = path.replace("\\", "/")
    return unified.lower() if IS_WINDOWS else unified


def _normcase(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_unc(path: str) -> bool:
    """True if ``path`` is a UNC path (``\\\\server\\share`` or ``//server/share``)."""
    unified = path.replace("\\", "/")
    return unified.startswith("//")


def is_within_root(real_root: str, real_path: str) -> bool:
    """True if ``real_path`` is the root or lies beneath it (case-insensitive on Windows)."""
    root = _normcase(real_root)
    candidate = _normcase(real_path)
    if candidate == root:
        return True
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        # Different drives / mixed absolute-relative: not comparable, treat as outside.
        return False


@dataclass(frozen=True)
class NormalizedRoot:
    """A validated repository root."""

    display_path: str  # absolute, original casing
    normalized_path: str  # comparison key
    real_path: str  # junctions/symlinks resolved
    path: Path  # Path(display_path), for walking


def normalize_root(raw_path: str | os.PathLike[str], *, allow_unc: bool = False) -> NormalizedRoot:
    """Validate and normalize a repository root path.

    Raises :class:`UnsupportedPathError` for disallowed UNC paths and
    :class:`RepositoryError` for missing/unreadable directories.
    """
    raw = os.fspath(raw_path)
    expanded = os.path.expanduser(raw)

    if is_unc(expanded) and not allow_unc:
        raise UnsupportedPathError(f"UNC path not allowed without explicit opt-in: {raw!r}")

    display = os.path.abspath(expanded)
    real = os.path.realpath(expanded)

    if not os.path.exists(real):
        raise RepositoryError(f"Repository path does not exist: {display!r}")
    if not os.path.isdir(real):
        raise RepositoryError(f"Repository path is not a directory: {display!r}")
    if not os.access(real, os.R_OK):
        raise PathSecurityError(f"Repository path is not readable: {display!r}")

    return NormalizedRoot(
        display_path=display,
        normalized_path=normalize_key(display),
        real_path=real,
        path=Path(display),
    )


@dataclass(frozen=True)
class ReparseInfo:
    """Result of inspecting a directory child for reparse-point behaviour."""

    is_reparse: bool  # symlink or junction
    escapes_root: bool  # its real target lies outside the repository root
    real_target: str


def inspect_child(*, parent_dir: str, name: str, real_root: str) -> ReparseInfo:
    """Detect whether ``parent_dir/name`` is a reparse point and whether it escapes root.

    Works for both POSIX symlinks and Windows junctions by comparing the child's
    resolved real path against the path it *would* have if it were a plain entry.
    """
    child_abs = os.path.join(parent_dir, name)
    real_target = os.path.realpath(child_abs)
    expected = os.path.join(os.path.realpath(parent_dir), name)
    is_reparse = _normcase(real_target) != _normcase(expected)
    escapes = is_reparse and not is_within_root(real_root, real_target)
    return ReparseInfo(is_reparse=is_reparse, escapes_root=escapes, real_target=real_target)


def read_bytes(path: str, *, long_paths_enabled: bool = True) -> bytes:
    r"""Read a file's bytes, applying the Windows ``\\?\`` long-path prefix when needed."""
    target = path
    if IS_WINDOWS and long_paths_enabled:
        absolute = os.path.abspath(path)
        if len(absolute) >= _LONG_PATH_THRESHOLD and not absolute.startswith("\\\\?\\"):
            target = "\\\\?\\" + absolute
    with open(target, "rb") as handle:
        return handle.read()
