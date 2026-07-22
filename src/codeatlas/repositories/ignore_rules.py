"""Ignore-rules engine (Blueprint §4.3.3, CLAUDE.md §12).

Precedence (first listed is applied first; within the combined list the *last*
matching pattern wins, honouring gitignore negation):

    .gitignore -> .codeatlasignore -> built-ins -> user config

A hard non-exclusion guarantee overrides everything: files matching the
``never_exclude`` globs (lockfiles, migrations, OpenAPI, SQL, Dockerfiles, CI
config) are always scanned because they matter for impact analysis.

This implements a focused, well-tested subset of gitignore semantics: comments,
negation (``!``), directory-only (trailing ``/``), root anchoring (leading or
embedded ``/``), ``*``/``?`` within a segment, ``**`` across segments, and
basename matching for unanchored patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

# Built-in default exclusions (Blueprint §4.3.3).
BUILTIN_IGNORE_PATTERNS: tuple[str, ...] = (
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


def _translate(pattern: str) -> str:
    """Translate one gitignore glob body (no leading ``!``/anchor) into a regex fragment."""
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # '**' — consume, and an adjacent '/' so 'a/**/b' also matches 'a/b'.
                i += 2
                if i < n and pattern[i] == "/":
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "/":
            out.append("/")
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class _Rule:
    regex: re.Pattern[str]
    negated: bool
    dir_only: bool


def _compile(pattern_line: str) -> _Rule | None:
    """Compile a single ignore-file line into a rule, or ``None`` for blank/comment lines."""
    line = pattern_line.rstrip("\n")
    # A trailing space is only literal if backslash-escaped; otherwise strip it.
    if not line.endswith("\\ "):
        line = line.rstrip()
    if not line or line.startswith("#"):
        return None

    negated = False
    if line.startswith("!"):
        negated = True
        line = line[1:]

    dir_only = line.endswith("/")
    if dir_only:
        line = line[:-1]

    anchored = line.startswith("/")
    if anchored:
        line = line[1:]
    # A slash anywhere (other than a trailing one) anchors the pattern to the root.
    anchored = anchored or "/" in line

    body = _translate(line)
    if anchored:
        regex = re.compile(rf"^{body}(?:/.*)?$")
    else:
        # Match at any depth: either the full relative path or any trailing segment(s).
        regex = re.compile(rf"(?:^|.*/){body}(?:/.*)?$")
    return _Rule(regex=regex, negated=negated, dir_only=dir_only)


def _compile_all(patterns: tuple[str, ...]) -> tuple[_Rule, ...]:
    rules: list[_Rule] = []
    for pattern in patterns:
        rule = _compile(pattern)
        if rule is not None:
            rules.append(rule)
    return tuple(rules)


class IgnoreEngine:
    """Evaluates ignore rules against repository-relative POSIX paths."""

    def __init__(
        self,
        *,
        gitignore: tuple[str, ...] = (),
        codeatlasignore: tuple[str, ...] = (),
        builtins: tuple[str, ...] = BUILTIN_IGNORE_PATTERNS,
        user: tuple[str, ...] = (),
        never_exclude_globs: tuple[str, ...] = (),
    ) -> None:
        # Combined in precedence order; last match wins (gitignore semantics).
        self._rules = _compile_all(gitignore + codeatlasignore + builtins + user)
        self._never_exclude = never_exclude_globs

    @classmethod
    def for_repository(
        cls,
        root: Path,
        *,
        user_patterns: tuple[str, ...] = (),
        never_exclude_globs: tuple[str, ...] = (),
    ) -> IgnoreEngine:
        """Build an engine, reading ``.gitignore`` / ``.codeatlasignore`` from the root."""
        return cls(
            gitignore=_read_ignore_file(root / ".gitignore"),
            codeatlasignore=_read_ignore_file(root / ".codeatlasignore"),
            user=user_patterns,
            never_exclude_globs=never_exclude_globs,
        )

    def _is_never_excluded(self, relative_posix: str) -> bool:
        return any(
            fnmatch(relative_posix, glob) or fnmatch("/" + relative_posix, glob)
            for glob in self._never_exclude
        )

    def is_ignored(self, relative_posix: str, *, is_dir: bool) -> bool:
        """Return whether a repository-relative path is ignored.

        The non-exclusion guarantee wins over all rules (files only — a directory
        may still be pruned, but its never-excluded members are re-checked when
        the walker descends only into non-ignored directories).
        """
        if not is_dir and self._is_never_excluded(relative_posix):
            return False

        ignored = False
        for rule in self._rules:
            if rule.dir_only and not is_dir:
                continue
            if rule.regex.search(relative_posix):
                ignored = not rule.negated
        return ignored


def _read_ignore_file(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return ()
    return tuple(text.splitlines())
