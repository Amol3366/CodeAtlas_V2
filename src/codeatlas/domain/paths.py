"""Canonicalization and containment rules for approved repository roots.

Every path that reaches storage, evidence, or an adapter passes through here
first. The rules are deliberately strict: a path is either provably inside the
approved root and expressible as a normalized repository-relative path, or it is
rejected. Relative-path validity is delegated to the ``RepositoryRelativePath``
contract rule so that one definition governs storage, evidence, and the
evaluation corpus alike.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter, ValidationError

from codeatlas.contracts import RepositoryRelativePath
from codeatlas.domain.errors import PathOutsideRootError, PathSafetyError

_RELATIVE_PATH_ADAPTER: TypeAdapter[str] = TypeAdapter(RepositoryRelativePath)
_CASE_INSENSITIVE_FILESYSTEM = os.name == "nt"


def validate_relative_path(value: str) -> str:
    """Validate a repository-relative path against the public contract rule."""
    try:
        return _RELATIVE_PATH_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise PathSafetyError(
            "The path is not a normalized repository-relative path."
        ) from error


def canonicalize_root(raw_path: str) -> Path:
    """Resolve and validate an approved repository root.

    Rejects blank input, UNC roots, paths that do not exist, and paths that are
    not directories. UNC support is deliberately withheld: the blueprint allows
    it only behind an explicit opt-in that does not exist yet.
    """
    candidate = raw_path.strip()
    if not candidate:
        raise PathSafetyError("A repository path is required.")

    if _CASE_INSENSITIVE_FILESYSTEM and candidate.replace("/", "\\").startswith("\\\\"):
        raise PathSafetyError("UNC repository paths are not supported.")

    try:
        resolved = Path(candidate).resolve(strict=True)
    except OSError as error:
        raise PathSafetyError("The repository path could not be resolved.") from error

    if not resolved.is_dir():
        raise PathSafetyError("The repository path must be an existing directory.")
    return resolved


def is_inside_root(root: Path, candidate: Path) -> bool:
    """Return whether ``candidate`` resolves to ``root`` or below it.

    Both sides are fully resolved first, so a symlink or Windows junction whose
    target lies outside the root returns ``False`` even though its own path
    looks contained.
    """
    resolved_root = Path(os.path.realpath(root))
    resolved_candidate = Path(os.path.realpath(candidate))

    root_parts = _comparison_parts(resolved_root)
    candidate_parts = _comparison_parts(resolved_candidate)
    return candidate_parts[: len(root_parts)] == root_parts


def normalize_relative_path(root: Path, target: Path) -> str:
    """Return the validated repository-relative POSIX path of ``target``.

    Raises :class:`PathSafetyError` when the target is the root itself, escapes
    the root, or cannot be expressed as a contract-valid relative path.
    """
    if not is_inside_root(root, target):
        raise PathSafetyError("The path resolves outside the repository root.")

    resolved_root = Path(os.path.realpath(root))
    resolved_target = Path(os.path.realpath(target))
    if _comparison_parts(resolved_target) == _comparison_parts(resolved_root):
        raise PathSafetyError("The repository root itself is not a file path.")

    relative = resolved_target.relative_to(resolved_root)
    normalized = unicodedata.normalize("NFC", PurePosixPath(*relative.parts).as_posix())
    return validate_relative_path(normalized)


def resolve_inside_root(root: Path, relative_path: str) -> Path:
    """Resolve a repository-relative path to an absolute path inside ``root``.

    The relative path is contract-validated before it touches the filesystem, and
    the resolved result is containment-checked afterwards, so neither a malformed
    input nor a link target can escape.
    """
    validated = validate_relative_path(relative_path)
    candidate = root.joinpath(*PurePosixPath(validated).parts)
    if not is_inside_root(root, candidate):
        raise PathOutsideRootError("The path resolves outside the repository root.")
    return candidate


def _comparison_parts(path: Path) -> tuple[str, ...]:
    """Return path parts normalized for comparison on the host filesystem."""
    parts = path.parts
    if _CASE_INSENSITIVE_FILESYSTEM:
        return tuple(part.casefold() for part in parts)
    return parts
