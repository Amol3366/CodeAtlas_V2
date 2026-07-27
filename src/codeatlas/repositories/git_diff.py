"""Read-only Git diff and blob adapter.

Security rules mirror ``codeatlas.repositories.git_state``:

* every invocation passes an argument array with ``shell=False``;
* the repository is selected with ``cwd``;
* refs are validated against a strict grammar before becoming arguments;
* paths read from Git output are untrusted and pass ``validate_relative_path``
  containment before use;
* only read-only plumbing commands are used, with an explicit timeout and
  disabled prompting/optional locks.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codeatlas.domain.errors import (
    GitRefUnresolvableError,
    ScanLimitExceededError,
)
from codeatlas.domain.paths import validate_relative_path
from codeatlas.domain.repository import ScanLimits

GIT_TIMEOUT_SECONDS: float = 10.0
_REF_PATTERN = re.compile(
    r"^[0-9a-f]{40}$|^(HEAD(~\d+)?|[A-Za-z0-9][A-Za-z0-9._/-]{0,127})$"
)
_ChangeKind = Literal["added", "deleted", "modified", "renamed"]


@dataclass(frozen=True)
class ChangedFileEntry:
    """One file-level change between a base and a target state."""

    relative_path: str
    base_path: str | None
    change_kind: _ChangeKind
    base_content_hash: str | None
    target_content_hash: str | None


class GitDiffAdapter:
    """Reads Git diff metadata and blobs from a repository root."""

    def __init__(
        self,
        git_executable: str = "git",
        timeout_seconds: float = GIT_TIMEOUT_SECONDS,
        limits: ScanLimits | None = None,
    ) -> None:
        self._git_executable = git_executable
        self._timeout_seconds = timeout_seconds
        self._limits = limits or ScanLimits()

    def resolve_ref(self, root: Path, ref: str) -> str:
        """Return the 40-hex commit SHA for ``ref``.

        Raises :class:`GitRefUnresolvableError` when the ref is syntactically
        invalid or does not resolve to a commit.
        """
        self._validate_ref(ref)
        stdout, failure = self._run(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if failure is not None or stdout is None:
            raise GitRefUnresolvableError(
                f"The ref {ref!r} could not be resolved to a commit.",
                details={"ref": ref},
            )
        resolved = stdout.strip()
        if len(resolved) != 40 or not all(
            character in "0123456789abcdef" for character in resolved
        ):
            raise GitRefUnresolvableError(
                f"The ref {ref!r} resolved to unexpected output.",
                details={"ref": ref, "output": resolved},
            )
        return resolved

    def changed_files(
        self,
        root: Path,
        base: str,
        target: str | None,
    ) -> tuple[ChangedFileEntry, ...]:
        """Return file-level changes between ``base`` and ``target``.

        ``target=None`` means the working tree. Rename detection is performed
        by content-hash equality only; Git's similarity score never grounds a
        rename finding.
        """
        self._validate_ref(base)
        if target is not None:
            self._validate_ref(target)

        args = ["diff", "--name-status", "--no-renames", base]
        if target is not None:
            args.append(target)
        stdout, failure = self._run(root, *args)
        if failure is not None or stdout is None:
            raise GitRefUnresolvableError(
                "Could not read the changed-file list.",
                details={"base": base, "target": target or "working-tree"},
            )

        raw: list[tuple[_ChangeKind, str]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parsed = self._parse_name_status_line(line)
            if parsed is None:
                continue
            raw.append(parsed)

        deleted: list[tuple[str, str]] = []  # (path, base_hash)
        added: list[tuple[str, str]] = []    # (path, target_hash)
        modified: list[ChangedFileEntry] = []

        for kind, path in raw:
            validated_path = self._validate_output_path(path)
            if validated_path is None:
                continue

            if kind == "added":
                target_hash = self._hash_at_target(root, target, validated_path)
                added.append((validated_path, target_hash))
            elif kind == "deleted":
                base_hash = self._hash_at_base(root, base, validated_path)
                deleted.append((validated_path, base_hash))
            else:  # modified
                base_hash = self._hash_at_base(root, base, validated_path)
                target_hash = self._hash_at_target(root, target, validated_path)
                modified.append(
                    ChangedFileEntry(
                        relative_path=validated_path,
                        base_path=None,
                        change_kind="modified",
                        base_content_hash=base_hash,
                        target_content_hash=target_hash,
                    )
                )

        entries = list(modified)
        rename_pairs = self._pair_renames(deleted, added)
        used_deleted: set[int] = set()
        used_added: set[int] = set()

        for deleted_index, added_index in rename_pairs:
            deleted_path, deleted_hash = deleted[deleted_index]
            added_path, added_hash = added[added_index]
            entries.append(
                ChangedFileEntry(
                    relative_path=added_path,
                    base_path=deleted_path,
                    change_kind="renamed",
                    base_content_hash=deleted_hash,
                    target_content_hash=added_hash,
                )
            )
            used_deleted.add(deleted_index)
            used_added.add(added_index)

        for index, (path, base_hash) in enumerate(deleted):
            if index not in used_deleted:
                entries.append(
                    ChangedFileEntry(
                        relative_path=path,
                        base_path=None,
                        change_kind="deleted",
                        base_content_hash=base_hash,
                        target_content_hash=None,
                    )
                )

        for index, (path, target_hash) in enumerate(added):
            if index not in used_added:
                entries.append(
                    ChangedFileEntry(
                        relative_path=path,
                        base_path=None,
                        change_kind="added",
                        base_content_hash=None,
                        target_content_hash=target_hash,
                    )
                )

        entries.sort(key=lambda item: item.relative_path)
        return tuple(entries)

    def read_blob(self, root: Path, ref: str, relative_path: str) -> bytes | None:
        """Return the bytes of ``relative_path`` at ``ref``.

        Returns ``None`` when the path does not exist at that ref. Oversized
        blobs raise :class:`ScanLimitExceededError`.
        """
        self._validate_ref(ref)
        validate_relative_path(relative_path)

        size_args = ["cat-file", "-s", f"{ref}:{relative_path}"]
        size_stdout, size_failure = self._run(root, *size_args)
        if size_failure is not None or size_stdout is None:
            return None
        try:
            size = int(size_stdout.strip())
        except ValueError:
            return None
        if size > self._limits.max_file_bytes:
            raise ScanLimitExceededError(
                "The blob exceeds the configured maximum file size.",
                details={
                    "relative_path": relative_path,
                    "size_bytes": str(size),
                    "max_file_bytes": str(self._limits.max_file_bytes),
                },
            )

        stdout, failure = self._run_bytes(root, "show", f"{ref}:{relative_path}")
        if failure is not None or stdout is None:
            return None
        return stdout

    def list_files(self, root: Path, ref: str) -> tuple[str, ...]:
        """Return the tracked file paths at ``ref`` in deterministic order."""
        self._validate_ref(ref)
        stdout, failure = self._run(root, "ls-tree", "-r", "--name-only", ref)
        if failure is not None or stdout is None:
            raise GitRefUnresolvableError(
                f"Could not list files for ref {ref!r}.",
                details={"ref": ref},
            )

        paths: list[str] = []
        for line in stdout.splitlines():
            path = line.strip()
            if not path:
                continue
            validated = self._validate_output_path(path)
            if validated is not None:
                paths.append(validated)
        paths.sort()
        return tuple(paths)

    def _validate_ref(self, ref: str) -> None:
        """Raise when a ref is not safe to pass to Git."""
        if not ref or "\x00" in ref or ".." in ref or ref.startswith("-"):
            raise GitRefUnresolvableError(
                f"The ref {ref!r} is not a valid Git ref.",
                details={"ref": ref},
            )
        if not _REF_PATTERN.match(ref):
            raise GitRefUnresolvableError(
                f"The ref {ref!r} does not match the allowed ref grammar.",
                details={"ref": ref},
            )

    def _validate_output_path(self, path: str) -> str | None:
        """Return the validated path, or ``None`` if it escapes the repository."""
        try:
            return validate_relative_path(path)
        except Exception:
            return None

    def _parse_name_status_line(
        self, line: str
    ) -> tuple[_ChangeKind, str] | None:
        """Parse one line of ``git diff --name-status`` output.

        Only single-character statuses are expected because ``--no-renames``
        disables the multi-column rename output.
        """
        if not line:
            return None
        status = line[0]
        path_part = line[1:].strip()
        if not path_part:
            return None
        if status == "A":
            return ("added", path_part)
        if status == "D":
            return ("deleted", path_part)
        if status == "M":
            return ("modified", path_part)
        # Ignore unexpected statuses rather than crashing; they cannot be
        # interpreted safely without a versioned parser.
        return None

    def _hash_at_base(
        self, root: Path, base: str, relative_path: str
    ) -> str:
        blob = self.read_blob(root, base, relative_path)
        if blob is None:
            return ""
        return _hash_bytes(blob)

    def _hash_at_target(
        self, root: Path, target: str | None, relative_path: str
    ) -> str:
        if target is None:
            return self._hash_working_tree_file(root, relative_path)
        blob = self.read_blob(root, target, relative_path)
        if blob is None:
            return ""
        return _hash_bytes(blob)

    def _hash_working_tree_file(self, root: Path, relative_path: str) -> str:
        target = root.joinpath(*relative_path.split("/"))
        try:
            content = target.read_bytes()
        except (FileNotFoundError, PermissionError, OSError):
            return ""
        if len(content) > self._limits.max_file_bytes:
            raise ScanLimitExceededError(
                "The working-tree file exceeds the configured maximum file size.",
                details={"relative_path": relative_path},
            )
        return _hash_bytes(content)

    def _pair_renames(
        self,
        deleted: list[tuple[str, str]],
        added: list[tuple[str, str]],
    ) -> list[tuple[int, int]]:
        """Pair deleted and added files by unique content-hash equality.

        If more than one deleted file shares a hash, none of them may be treated
        as a rename; the match is ambiguous and ambiguity degrades to delete+add.
        """
        hash_to_deleted: dict[str, list[int]] = {}
        for index, (_, content_hash) in enumerate(deleted):
            if not content_hash:
                continue
            hash_to_deleted.setdefault(content_hash, []).append(index)

        unique_hash_to_deleted = {
            content_hash: indices[0]
            for content_hash, indices in hash_to_deleted.items()
            if len(indices) == 1
        }

        pairs: list[tuple[int, int]] = []
        used_hashes: set[str] = set()
        for added_index, (_, content_hash) in enumerate(added):
            if not content_hash or content_hash in used_hashes:
                continue
            deleted_index = unique_hash_to_deleted.get(content_hash)
            if deleted_index is not None:
                pairs.append((deleted_index, added_index))
                used_hashes.add(content_hash)

        pairs.sort()
        return pairs

    def _run(self, root: Path, *arguments: str) -> tuple[str | None, str | None]:
        try:
            completed = subprocess.run(
                [self._git_executable, *arguments],
                cwd=str(root),
                shell=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_OPTIONAL_LOCKS": "0",
                },
            )
        except FileNotFoundError:
            return None, "GIT_EXECUTABLE_UNAVAILABLE"
        except subprocess.TimeoutExpired:
            return None, "GIT_TIMEOUT"
        except OSError:
            return None, "GIT_EXECUTABLE_UNAVAILABLE"

        if completed.returncode != 0:
            return None, None
        return completed.stdout, None

    def _run_bytes(
        self, root: Path, *arguments: str
    ) -> tuple[bytes | None, str | None]:
        try:
            completed = subprocess.run(
                [self._git_executable, *arguments],
                cwd=str(root),
                shell=False,
                capture_output=True,
                text=False,
                timeout=self._timeout_seconds,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_OPTIONAL_LOCKS": "0",
                },
            )
        except FileNotFoundError:
            return None, "GIT_EXECUTABLE_UNAVAILABLE"
        except subprocess.TimeoutExpired:
            return None, "GIT_TIMEOUT"
        except OSError:
            return None, "GIT_EXECUTABLE_UNAVAILABLE"

        if completed.returncode != 0:
            return None, None
        return completed.stdout, None


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
