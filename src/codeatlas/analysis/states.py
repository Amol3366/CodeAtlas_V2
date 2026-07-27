"""StateView implementations: Directory, GitBlob, Snapshot.

A :class:`StateView` is one side of a change: it exposes the files of that side
(relative path, language, classification, content hash, size, line count) and
can read their bytes. The engine never cares *how* the bytes were produced —
from disk, from Git, or from a stored snapshot — so the three implementations are
interchangeable.

Security notes:

* Directory reads are containment-checked against the approved root.
* GitBlob reads reuse the same argument-array, ``shell=False``, ref-validating
  adapter that Phase 4's Git front-end uses.
* Snapshot reads re-verify the stored content hash against the file on disk, so
  a drifted working tree cannot pass as the snapshot it claims to be.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from codeatlas.domain.change import StateFile
from codeatlas.domain.errors import PathOutsideRootError, PathSafetyError
from codeatlas.domain.paths import resolve_inside_root, validate_relative_path
from codeatlas.domain.repository import FileClassification, ScanLimits
from codeatlas.repositories.git_diff import GitDiffAdapter
from codeatlas.repositories.ignore_rules import IgnoreRules
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.storage.sqlite.stores import FileStore


class StateView(Protocol):
    """One side of a change: a read-only collection of files."""

    def list_files(self) -> tuple[StateFile, ...]:
        """Return every file in this state, in deterministic order."""
        ...

    def read_file(self, relative_path: str) -> bytes | None:
        """Read ``relative_path`` and verify it matches the state's hash.

        Returns ``None`` when the path is absent, escapes the root, is unreadable,
        or has drifted from the hash the state claims.
        """
        ...


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class DirectoryStateView:
    """A state backed by a directory on disk.

    The directory is scanned with the same ignore rules and limits as an ordinary
    repository scan. Read requests are containment-checked and hash-verified.
    """

    def __init__(self, root: Path, limits: ScanLimits | None = None) -> None:
        self._root = root
        self._limits = limits or ScanLimits()
        self._files_by_path: dict[str, StateFile] | None = None

    def list_files(self) -> tuple[StateFile, ...]:
        if self._files_by_path is None:
            rules = IgnoreRules.load(self._root)
            scanner = RepositoryScanner(limits=self._limits)
            scan = scanner.scan(self._root, rules)
            self._files_by_path = {
                record.relative_path: StateFile(
                    relative_path=record.relative_path,
                    language=record.language,
                    classification=record.classification,
                    content_hash=record.content_hash,
                    size_bytes=record.size_bytes,
                    line_count=record.line_count,
                )
                for record in scan.files
            }
        files = list(self._files_by_path.values())
        files.sort(key=lambda file: file.relative_path)
        return tuple(files)

    def read_file(self, relative_path: str) -> bytes | None:
        state_file = self._get(relative_path)
        if state_file is None:
            return None
        content = self._read(relative_path)
        if content is None:
            return None
        if _hash_bytes(content) != state_file.content_hash:
            return None
        return content

    def _get(self, relative_path: str) -> StateFile | None:
        try:
            validate_relative_path(relative_path)
        except PathSafetyError:
            return None
        self.list_files()
        assert self._files_by_path is not None
        return self._files_by_path.get(relative_path)

    def _read(self, relative_path: str) -> bytes | None:
        try:
            return resolve_inside_root(self._root, relative_path).read_bytes()
        except (OSError, ValueError):
            return None


class GitBlobStateView:
    """A state backed by Git objects at a resolved ref.

    Files are listed with ``git ls-tree`` and read with ``git show``. Every read
    is hash-verified against the hash computed at listing time, so a corrupt or
    raced read cannot silently produce wrong bytes.
    """

    def __init__(
        self,
        root: Path,
        ref: str,
        git: GitDiffAdapter | None = None,
    ) -> None:
        self._root = root
        self._ref = ref
        self._git = git or GitDiffAdapter()
        self._files_by_path: dict[str, StateFile] | None = None

    def list_files(self) -> tuple[StateFile, ...]:
        if self._files_by_path is None:
            paths = self._git.list_files(self._root, self._ref)
            files: list[StateFile] = []
            for path in paths:
                content = self._git.read_blob(self._root, self._ref, path)
                if content is None:
                    continue
                classification, language = self._classify(path)
                files.append(
                    StateFile(
                        relative_path=path,
                        language=language,
                        classification=classification,
                        content_hash=_hash_bytes(content),
                        size_bytes=len(content),
                        line_count=_count_lines(content),
                    )
                )
            self._files_by_path = {file.relative_path: file for file in files}
        files = list(self._files_by_path.values())
        files.sort(key=lambda file: file.relative_path)
        return tuple(files)

    def read_file(self, relative_path: str) -> bytes | None:
        state_file = self._get(relative_path)
        if state_file is None:
            return None
        content = self._git.read_blob(self._root, self._ref, relative_path)
        if content is None:
            return None
        if _hash_bytes(content) != state_file.content_hash:
            return None
        return content

    def _get(self, relative_path: str) -> StateFile | None:
        try:
            validate_relative_path(relative_path)
        except PathSafetyError:
            return None
        self.list_files()
        assert self._files_by_path is not None
        return self._files_by_path.get(relative_path)

    @staticmethod

    def _classify(relative_path: str) -> tuple[FileClassification, str]:
        from codeatlas.repositories.classification import classify

        return classify(relative_path)


class SnapshotStateView:
    """A state backed by a stored snapshot's file rows.

    Only the file list comes from storage; bytes are read from disk and verified
    against the stored hash. This mirrors the evidence builder's drift discipline:
    a snapshot whose files have changed is reported as stale rather than cited as
    current.
    """

    def __init__(
        self,
        root: Path,
        snapshot_id: str,
        files: FileStore,
    ) -> None:
        self._root = root
        self._snapshot_id = snapshot_id
        self._files = files
        self._files_by_path: dict[str, StateFile] | None = None

    def list_files(self) -> tuple[StateFile, ...]:
        if self._files_by_path is None:
            records = self._files.list_for_snapshot(self._snapshot_id)
            self._files_by_path = {
                record.relative_path: StateFile(
                    relative_path=record.relative_path,
                    language=record.language,
                    classification=record.classification,
                    content_hash=record.content_hash,
                    size_bytes=record.size_bytes,
                    line_count=record.line_count,
                )
                for record in records
            }
        files = list(self._files_by_path.values())
        files.sort(key=lambda file: file.relative_path)
        return tuple(files)

    def read_file(self, relative_path: str) -> bytes | None:
        state_file = self._get(relative_path)
        if state_file is None:
            return None
        content = self._read(relative_path)
        if content is None:
            return None
        if _hash_bytes(content) != state_file.content_hash:
            return None
        return content

    def _get(self, relative_path: str) -> StateFile | None:
        try:
            validate_relative_path(relative_path)
        except PathSafetyError:
            return None
        self.list_files()
        assert self._files_by_path is not None
        return self._files_by_path.get(relative_path)


    def _read(self, relative_path: str) -> bytes | None:
        try:
            return resolve_inside_root(self._root, relative_path).read_bytes()
        except (OSError, PathOutsideRootError, PathSafetyError, ValueError):
            return None


def _count_lines(content: bytes) -> int:
    if not content:
        return 0
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")
    newline_count = text.count("\n")
    return newline_count if text.endswith("\n") else newline_count + 1
