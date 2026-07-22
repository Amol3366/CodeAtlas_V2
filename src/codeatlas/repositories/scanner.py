"""Windows-safe deterministic repository scanner (Blueprint §4.3, Phase 1).

Produces a stable, byte-reproducible file manifest plus first-class skip
diagnostics. Never executes repository code (CLAUDE.md §2.4) — it only reads
bytes. Symlinks/junctions are inspected but never followed outside the root.

Key guarantees:
- deterministic ordering (entries sorted by normalized path);
- content-addressed identity via SHA-256 over normalized content
  (CRLF/CR -> LF and BOM stripping for text; raw bytes for binary);
- every skipped file carries a reason;
- ``diff_manifests`` classifies added/modified/deleted/renamed between scans.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

import orjson

from codeatlas.domain.enums import FileClassification, Language
from codeatlas.logging.setup import get_logger
from codeatlas.repositories import path_security as ps
from codeatlas.repositories.classifier import classify
from codeatlas.repositories.ignore_rules import IgnoreEngine
from codeatlas.settings.config import LanguageIndex, ScanConfig

_MANIFEST_FORMAT_VERSION = 1
_BINARY_SNIFF_BYTES = 8192

_BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".tiff",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".7z",
        ".rar",
        ".jar",
        ".war",
        ".dll",
        ".exe",
        ".so",
        ".dylib",
        ".class",
        ".pyc",
        ".pyo",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".wav",
        ".flac",
        ".db",
        ".sqlite",
        ".bin",
        ".dat",
    }
)


class SkipReason(StrEnum):
    """Why a path was skipped (first-class diagnostics, not silent skips)."""

    IGNORED = "ignored"
    TOO_LARGE = "too_large"
    UNREADABLE = "unreadable"
    SYMLINK_ESCAPE = "symlink_escape"  # reparse point whose target leaves the root
    SYMLINK_SKIPPED = "symlink_skipped"  # reparse point inside root (not followed, avoids cycles)


@dataclass(frozen=True)
class ManifestEntry:
    """One scanned file. ``display_path`` keeps casing; ``normalized_path`` is the key."""

    display_path: str
    normalized_path: str
    content_hash: str
    classification: FileClassification
    language: Language | None
    size_bytes: int
    line_count: int
    is_binary: bool


@dataclass(frozen=True)
class SkippedFile:
    """A path excluded from the manifest, with a reason."""

    display_path: str
    reason: SkipReason
    detail: str | None = None


@dataclass(frozen=True)
class ScanManifest:
    """Deterministic set of manifest entries (sorted by normalized path)."""

    normalization_version: str
    entries: tuple[ManifestEntry, ...]

    def to_json(self) -> bytes:
        """Serialize to stable, byte-reproducible JSON (sorted keys, sorted entries)."""
        payload = {
            "format_version": _MANIFEST_FORMAT_VERSION,
            "normalization_version": self.normalization_version,
            "entries": [
                {
                    "path": entry.display_path,
                    "normalized_path": entry.normalized_path,
                    "content_hash": entry.content_hash,
                    "classification": entry.classification.value,
                    "language": entry.language.value if entry.language else None,
                    "size_bytes": entry.size_bytes,
                    "line_count": entry.line_count,
                    "is_binary": entry.is_binary,
                }
                for entry in self.entries
            ],
        }
        return orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)

    def by_path(self) -> dict[str, ManifestEntry]:
        return {entry.normalized_path: entry for entry in self.entries}


@dataclass(frozen=True)
class ScanResult:
    """Result of a scan: the manifest plus ordered skip diagnostics."""

    manifest: ScanManifest
    skipped: tuple[SkippedFile, ...]


@dataclass(frozen=True)
class ManifestDiff:
    """Change detection between two manifests (renames paired by content hash)."""

    added: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]
    renamed: tuple[tuple[str, str], ...]  # (old_display_path, new_display_path)


def _strip_bom(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:]
    return raw


def _normalize_newlines(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _normalized_bytes(raw: bytes, *, is_binary: bool) -> bytes:
    if is_binary:
        return raw
    return _normalize_newlines(_strip_bom(raw))


def content_hash(raw: bytes, *, is_binary: bool) -> str:
    """SHA-256 over normalized content (CLAUDE.md §5 identity: pure hash of content)."""
    return hashlib.sha256(_normalized_bytes(raw, is_binary=is_binary)).hexdigest()


def detect_binary(raw: bytes, ext: str) -> bool:
    if ext.lower() in _BINARY_EXTENSIONS:
        return True
    return b"\x00" in raw[:_BINARY_SNIFF_BYTES]


def count_lines(raw: bytes, *, is_binary: bool) -> int:
    if is_binary or not raw:
        return 0
    data = _normalize_newlines(raw)
    lines = data.count(b"\n")
    if not data.endswith(b"\n"):
        lines += 1
    return lines


class RepositoryScanner:
    """Scans a normalized repository root into a deterministic manifest."""

    def __init__(self, config: ScanConfig, language_index: LanguageIndex) -> None:
        self._config = config
        self._language_index = language_index

    def scan(
        self,
        root: ps.NormalizedRoot,
        *,
        repository_id: str | None = None,
    ) -> ScanResult:
        log = get_logger(repository_id=repository_id) if repository_id else get_logger()
        ignore = IgnoreEngine.for_repository(
            root.path,
            user_patterns=self._config.user_ignore_patterns,
            never_exclude_globs=self._language_index.never_exclude_globs,
        )
        entries: list[ManifestEntry] = []
        skipped: list[SkippedFile] = []
        self._walk(
            dir_abs=root.display_path,
            rel_prefix="",
            real_root=root.real_path,
            ignore=ignore,
            entries=entries,
            skipped=skipped,
        )
        entries.sort(key=lambda entry: entry.normalized_path)
        skipped.sort(key=lambda item: (item.reason.value, ps.normalize_key(item.display_path)))
        log.info(
            "scan.completed",
            file_count=len(entries),
            skipped_count=len(skipped),
        )
        return ScanResult(
            manifest=ScanManifest(
                normalization_version=self._config.normalization_version,
                entries=tuple(entries),
            ),
            skipped=tuple(skipped),
        )

    def _walk(
        self,
        *,
        dir_abs: str,
        rel_prefix: str,
        real_root: str,
        ignore: IgnoreEngine,
        entries: list[ManifestEntry],
        skipped: list[SkippedFile],
    ) -> None:
        try:
            with os.scandir(dir_abs) as scanner:
                children = list(scanner)
        except (PermissionError, OSError) as exc:
            skipped.append(SkippedFile(rel_prefix or ".", SkipReason.UNREADABLE, str(exc)))
            return

        children.sort(key=lambda entry: ps.normalize_key(entry.name))
        for child in children:
            rel = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
            try:
                is_dir = child.is_dir(follow_symlinks=False)
            except OSError as exc:
                skipped.append(SkippedFile(rel, SkipReason.UNREADABLE, str(exc)))
                continue

            reparse = ps.inspect_child(parent_dir=dir_abs, name=child.name, real_root=real_root)
            if reparse.is_reparse and not self._config.follow_external_junctions:
                reason = (
                    SkipReason.SYMLINK_ESCAPE
                    if reparse.escapes_root
                    else SkipReason.SYMLINK_SKIPPED
                )
                skipped.append(SkippedFile(rel, reason, reparse.real_target))
                continue

            if is_dir:
                if ignore.is_ignored(rel, is_dir=True):
                    skipped.append(SkippedFile(rel, SkipReason.IGNORED))
                    continue
                self._walk(
                    dir_abs=os.path.join(dir_abs, child.name),
                    rel_prefix=rel,
                    real_root=real_root,
                    ignore=ignore,
                    entries=entries,
                    skipped=skipped,
                )
            else:
                self._scan_file(
                    child_abs=os.path.join(dir_abs, child.name),
                    rel=rel,
                    ignore=ignore,
                    entries=entries,
                    skipped=skipped,
                )

    def _scan_file(
        self,
        *,
        child_abs: str,
        rel: str,
        ignore: IgnoreEngine,
        entries: list[ManifestEntry],
        skipped: list[SkippedFile],
    ) -> None:
        if ignore.is_ignored(rel, is_dir=False):
            skipped.append(SkippedFile(rel, SkipReason.IGNORED))
            return
        try:
            size = os.stat(child_abs, follow_symlinks=False).st_size
        except OSError as exc:
            skipped.append(SkippedFile(rel, SkipReason.UNREADABLE, str(exc)))
            return
        if size > self._config.max_file_size_bytes:
            skipped.append(SkippedFile(rel, SkipReason.TOO_LARGE, f"{size} bytes"))
            return
        try:
            raw = ps.read_bytes(child_abs, long_paths_enabled=self._config.long_paths_enabled)
        except OSError as exc:
            skipped.append(SkippedFile(rel, SkipReason.UNREADABLE, str(exc)))
            return

        ext = PurePosixPath(rel).suffix
        is_binary = detect_binary(raw, ext)
        language, classification = classify(
            rel, is_binary=is_binary, language_index=self._language_index
        )
        entries.append(
            ManifestEntry(
                display_path=rel,
                normalized_path=ps.normalize_key(rel),
                content_hash=content_hash(raw, is_binary=is_binary),
                classification=classification,
                language=language,
                size_bytes=size,
                line_count=count_lines(raw, is_binary=is_binary),
                is_binary=is_binary,
            )
        )


def diff_manifests(old: ScanManifest, new: ScanManifest) -> ManifestDiff:
    """Detect added/modified/deleted/renamed files between two manifests.

    Renames are inferred deterministically: a deleted path and an added path that
    share an identical content hash are paired (in sorted order) into a rename.
    """
    old_by = old.by_path()
    new_by = new.by_path()
    old_keys = set(old_by)
    new_keys = set(new_by)

    added_keys = sorted(new_keys - old_keys)
    deleted_keys = sorted(old_keys - new_keys)
    modified = sorted(
        key for key in old_keys & new_keys if old_by[key].content_hash != new_by[key].content_hash
    )

    # Pair pure add/delete pairs with identical content hashes as renames.
    deleted_by_hash: dict[str, list[str]] = {}
    for key in deleted_keys:
        deleted_by_hash.setdefault(old_by[key].content_hash, []).append(key)

    renamed: list[tuple[str, str]] = []
    consumed_added: set[str] = set()
    consumed_deleted: set[str] = set()
    for key in added_keys:
        candidates = deleted_by_hash.get(new_by[key].content_hash)
        if candidates:
            old_key = candidates.pop(0)
            consumed_added.add(key)
            consumed_deleted.add(old_key)
            renamed.append((old_by[old_key].display_path, new_by[key].display_path))

    added = tuple(new_by[key].display_path for key in added_keys if key not in consumed_added)
    deleted = tuple(old_by[key].display_path for key in deleted_keys if key not in consumed_deleted)
    return ManifestDiff(
        added=added,
        modified=tuple(new_by[key].display_path for key in modified),
        deleted=deleted,
        renamed=tuple(sorted(renamed)),
    )
