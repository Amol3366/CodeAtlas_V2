"""Ignore-rule evaluation for repository scanning.

Precedence, lowest to highest: built-in defaults, ``.gitignore``,
``.codeatlasignore``, then user-configured patterns. The last matching rule wins,
which is what makes a later ``!pattern`` negation able to re-include something an
earlier rule excluded.

Only a deliberate subset of gitignore syntax is supported. An unsupported pattern
is recorded as a warning and then ignored rather than approximated: silently
misapplying a rule would either hide files from repository truth or admit files
the user asked to exclude, and both are worse than an explicit gap.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git/",
    "node_modules/",
    "venv/",
    ".venv/",
    "__pycache__/",
    "dist/",
    "build/",
    "coverage/",
    ".next/",
    "target/",
    "bin/",
    "obj/",
    ".cache/",
    ".idea/",
    ".vscode/",
    "*.pyc",
    "*.pyo",
    "*.class",
    "*.dll",
    "*.exe",
    "*.so",
    "*.dylib",
    "*.min.js",
    "*.map",
)

# Impact analysis needs these even though build tooling often ignores them.
# They override the built-in defaults, but an explicit user or .codeatlasignore
# rule still wins.
NEVER_IGNORED_BASENAMES: tuple[str, ...] = (
    "uv.lock",
    "poetry.lock",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "Cargo.lock",
    "go.sum",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
)
_NEVER_IGNORED_SUFFIXES: tuple[str, ...] = (".sql",)
_NEVER_IGNORED_DIRECTORIES: tuple[str, ...] = ("migrations", ".github")

_UNSUPPORTED_MARKERS: tuple[str, ...] = ("**", "?", "[")


@dataclass(frozen=True)
class _Pattern:
    """One compiled ignore rule."""

    raw: str
    body: str
    negated: bool
    directory_only: bool
    root_anchored: bool
    source: str
    overrides_never_ignored: bool


class IgnoreRules:
    """Compiled ignore rules for one repository root."""

    def __init__(self, patterns: Sequence[_Pattern], warnings: Sequence[str]) -> None:
        self._patterns = tuple(patterns)
        self._warnings = tuple(warnings)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Diagnostics produced while compiling the rules."""
        return self._warnings

    @classmethod
    def load(cls, root: Path, user_patterns: Sequence[str] = ()) -> IgnoreRules:
        """Compile the effective rules for ``root`` in precedence order."""
        patterns: list[_Pattern] = []
        warnings: list[str] = []

        cls._compile_into(
            patterns, warnings, DEFAULT_IGNORE_PATTERNS, "builtin", overrides=False
        )
        pattern_files = (
            (".gitignore", "gitignore"),
            (".codeatlasignore", "codeatlasignore"),
        )
        for filename, source in pattern_files:
            lines = cls._read_pattern_file(root / filename, warnings)
            cls._compile_into(
                patterns,
                warnings,
                lines,
                source,
                overrides=source == "codeatlasignore",
            )
        cls._compile_into(patterns, warnings, user_patterns, "user", overrides=True)
        return cls(patterns, warnings)

    def is_ignored(self, relative_path: str, *, is_directory: bool) -> bool:
        """Return whether a repository-relative path is excluded from indexing."""
        decision = False
        decided_by_override = False

        for pattern in self._patterns:
            if not self._matches(pattern, relative_path, is_directory=is_directory):
                continue
            decision = not pattern.negated
            decided_by_override = pattern.overrides_never_ignored

        if decided_by_override or not decision:
            return decision
        return not self._is_never_ignored(relative_path)

    @staticmethod
    def _read_pattern_file(path: Path, warnings: list[str]) -> tuple[str, ...]:
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ()
        except (OSError, UnicodeDecodeError):
            warnings.append(f"IGNORE_FILE_UNREADABLE: {path.name}")
            return ()
        return tuple(content.splitlines())

    @classmethod
    def _compile_into(
        cls,
        patterns: list[_Pattern],
        warnings: list[str],
        lines: Sequence[str],
        source: str,
        *,
        overrides: bool,
    ) -> None:
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            negated = stripped.startswith("!")
            body = stripped[1:] if negated else stripped
            if any(marker in body for marker in _UNSUPPORTED_MARKERS):
                warnings.append(f"IGNORE_PATTERN_UNSUPPORTED: {source}: {stripped}")
                continue

            directory_only = body.endswith("/")
            body = body.rstrip("/")
            root_anchored = body.startswith("/")
            body = body.lstrip("/")
            if not body:
                warnings.append(f"IGNORE_PATTERN_UNSUPPORTED: {source}: {stripped}")
                continue

            patterns.append(
                _Pattern(
                    raw=stripped,
                    body=body,
                    negated=negated,
                    directory_only=directory_only,
                    root_anchored=root_anchored,
                    source=source,
                    overrides_never_ignored=overrides,
                )
            )

    @staticmethod
    def _matches(pattern: _Pattern, relative_path: str, *, is_directory: bool) -> bool:
        parts = PurePosixPath(relative_path).parts
        if not parts:
            return False

        if pattern.directory_only:
            # "docs/" excludes the directory and everything under it. Testing
            # every ancestor prefix makes that hold for a direct path query, not
            # only for a walker that stops descending.
            prefix_lengths = range(1, len(parts) + (1 if is_directory else 0))
        else:
            prefix_lengths = range(len(parts), len(parts) + 1)

        for length in prefix_lengths:
            prefix_parts = parts[:length]
            full = "/".join(prefix_parts)
            if pattern.root_anchored:
                candidates: tuple[str, ...] = (full,)
            elif "/" in pattern.body:
                # A pattern containing a separator matches the path or any of
                # its suffixes, so "docs/keep.md" matches at any depth.
                candidates = tuple(
                    "/".join(prefix_parts[index:]) for index in range(length)
                )
            else:
                candidates = (prefix_parts[-1], full)

            if any(fnmatchcase(candidate, pattern.body) for candidate in candidates):
                return True
        return False

    @staticmethod
    def _is_never_ignored(relative_path: str) -> bool:
        path = PurePosixPath(relative_path)
        if path.name in NEVER_IGNORED_BASENAMES:
            return True
        if path.suffix.lower() in _NEVER_IGNORED_SUFFIXES:
            return True
        return any(part in _NEVER_IGNORED_DIRECTORIES for part in path.parts[:-1])
