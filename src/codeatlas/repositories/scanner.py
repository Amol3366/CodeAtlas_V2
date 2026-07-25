"""Deterministic, bounded repository scanning.

The scanner reads a repository as untrusted data: it never imports, executes, or
evaluates anything it finds. Every entry either becomes a :class:`FileRecord` or
a :class:`SkippedFile` with a reason code, so nothing disappears silently.

Traversal is breadth-ordered by sorted path so two scans of an unchanged tree
produce identical output, including the working-tree fingerprint that later
determines snapshot identity.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from codeatlas.domain.errors import PathSafetyError, ScanLimitExceededError
from codeatlas.domain.ids import file_id, repository_id, stable_hash
from codeatlas.domain.paths import is_inside_root, validate_relative_path
from codeatlas.domain.repository import FileRecord, ScanLimits
from codeatlas.repositories.classification import classify
from codeatlas.repositories.ignore_rules import IgnoreRules

_BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class SkippedFile:
    """One entry excluded from the snapshot, with the reason it was excluded."""

    relative_path: str
    reason_code: str


@dataclass(frozen=True)
class ScanResult:
    """The deterministic outcome of one scan."""

    files: tuple[FileRecord, ...]
    skipped: tuple[SkippedFile, ...]
    warnings: tuple[str, ...]
    working_tree_fingerprint: str


class RepositoryScanner:
    """Walks an approved repository root within declared limits."""

    def __init__(self, limits: ScanLimits | None = None) -> None:
        self._limits = limits or ScanLimits()

    def scan(self, root: Path, rules: IgnoreRules) -> ScanResult:
        """Scan ``root`` and return its files, exclusions, and fingerprint."""
        repository = repository_id(str(root))
        files: list[FileRecord] = []
        skipped: list[SkippedFile] = []
        warnings: list[str] = list(rules.warnings)

        self._walk(
            root=root,
            directory=root,
            relative_prefix="",
            depth=0,
            rules=rules,
            repository=repository,
            files=files,
            skipped=skipped,
            warnings=warnings,
        )

        files.sort(key=lambda record: record.relative_path)
        skipped.sort(key=lambda record: (record.relative_path, record.reason_code))
        fingerprint = stable_hash(
            *(
                f"{record.relative_path}:{record.content_hash}:{record.size_bytes}"
                for record in files
            )
        )
        return ScanResult(
            files=tuple(files),
            skipped=tuple(skipped),
            warnings=tuple(warnings),
            working_tree_fingerprint=fingerprint,
        )

    def _walk(
        self,
        *,
        root: Path,
        directory: Path,
        relative_prefix: str,
        depth: int,
        rules: IgnoreRules,
        repository: str,
        files: list[FileRecord],
        skipped: list[SkippedFile],
        warnings: list[str],
    ) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except (PermissionError, OSError):
            directory_path = relative_prefix.rstrip("/") or "."
            skipped.append(SkippedFile(directory_path, "UNREADABLE"))
            return

        for entry in entries:
            entry_path = Path(entry.path)
            # The relative path is built from the walk, never from realpath, so
            # that a link's own name is reported before containment is decided.
            candidate = f"{relative_prefix}{entry.name}"
            relative = self._safe_relative(candidate)
            if relative is None:
                skipped.append(SkippedFile(candidate, "PATH_REJECTED"))
                continue

            if len(relative) > self._limits.max_relative_path_length:
                skipped.append(SkippedFile(relative, "PATH_REJECTED"))
                continue

            try:
                is_directory = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink() or entry.is_junction()
            except OSError:
                skipped.append(SkippedFile(relative, "UNREADABLE"))
                continue

            if rules.is_ignored(relative, is_directory=is_directory):
                skipped.append(SkippedFile(relative, "IGNORED"))
                continue

            if is_link:
                # A link is followed only when its resolved target is still
                # inside the approved root; otherwise it is an escape.
                if not is_inside_root(root, entry_path):
                    skipped.append(SkippedFile(relative, "OUTSIDE_ROOT"))
                    warnings.append(f"SECURITY_LINK_ESCAPE: {relative}")
                    continue
                is_directory = entry_path.is_dir()

            if is_directory:
                if depth + 1 > self._limits.max_depth:
                    skipped.append(SkippedFile(relative, "TOO_DEEP"))
                    continue
                self._walk(
                    root=root,
                    directory=entry_path,
                    relative_prefix=f"{relative}/",
                    depth=depth + 1,
                    rules=rules,
                    repository=repository,
                    files=files,
                    skipped=skipped,
                    warnings=warnings,
                )
                continue

            record = self._read_file(
                entry_path=entry_path,
                relative=relative,
                repository=repository,
                skipped=skipped,
            )
            if record is None:
                continue

            files.append(record)
            if len(files) > self._limits.max_files:
                raise ScanLimitExceededError(
                    "The repository exceeds the configured maximum file count.",
                    details={"max_files": str(self._limits.max_files)},
                )

    def _read_file(
        self,
        *,
        entry_path: Path,
        relative: str,
        repository: str,
        skipped: list[SkippedFile],
    ) -> FileRecord | None:
        try:
            size_bytes = entry_path.stat().st_size
        except OSError:
            skipped.append(SkippedFile(relative, "UNREADABLE"))
            return None

        if size_bytes > self._limits.max_file_bytes:
            skipped.append(SkippedFile(relative, "TOO_LARGE"))
            return None

        try:
            content = entry_path.read_bytes()
        except (PermissionError, OSError):
            skipped.append(SkippedFile(relative, "UNREADABLE"))
            return None

        if self._is_binary(content):
            skipped.append(SkippedFile(relative, "BINARY"))
            return None

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                skipped.append(SkippedFile(relative, "BINARY"))
                return None

        classification, language = classify(relative)
        return FileRecord(
            file_id=file_id(repository, relative),
            relative_path=relative,
            display_path=relative,
            content_hash=hashlib.sha256(content).hexdigest(),
            size_bytes=size_bytes,
            line_count=self._count_lines(text),
            language=language,
            classification=classification,
        )

    @staticmethod
    def _is_binary(content: bytes) -> bool:
        return b"\x00" in content[:_BINARY_SNIFF_BYTES]

    @staticmethod
    def _count_lines(text: str) -> int:
        if not text:
            return 0
        newline_count = text.count("\n")
        return newline_count if text.endswith("\n") else newline_count + 1

    @staticmethod
    def _safe_relative(candidate: str) -> str | None:
        """Validate a walk-built relative path against the contract rule."""
        try:
            return validate_relative_path(candidate)
        except PathSafetyError:
            return None
