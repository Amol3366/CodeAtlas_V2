"""Tests for the ignore-rules engine (Blueprint §4.3.3)."""

from __future__ import annotations

from codeatlas.repositories.ignore_rules import IgnoreEngine
from codeatlas.settings.config import default_language_index


def test_builtin_excludes_common_directories() -> None:
    engine = IgnoreEngine()
    assert engine.is_ignored("node_modules", is_dir=True)
    assert engine.is_ignored(".git", is_dir=True)
    assert engine.is_ignored("__pycache__", is_dir=True)
    assert engine.is_ignored("src/mod.pyc", is_dir=False)
    assert engine.is_ignored("dist", is_dir=True)


def test_builtin_does_not_exclude_source() -> None:
    engine = IgnoreEngine()
    assert not engine.is_ignored("src/app.py", is_dir=False)
    assert not engine.is_ignored("src", is_dir=True)


def test_directory_only_pattern_does_not_match_file() -> None:
    engine = IgnoreEngine(builtins=(), gitignore=("build/",))
    assert engine.is_ignored("build", is_dir=True)
    assert not engine.is_ignored("build", is_dir=False)


def test_anchored_pattern() -> None:
    engine = IgnoreEngine(builtins=(), gitignore=("/secret.txt",))
    assert engine.is_ignored("secret.txt", is_dir=False)
    assert not engine.is_ignored("sub/secret.txt", is_dir=False)


def test_unanchored_pattern_matches_at_any_depth() -> None:
    engine = IgnoreEngine(builtins=(), gitignore=("secret.txt",))
    assert engine.is_ignored("secret.txt", is_dir=False)
    assert engine.is_ignored("a/b/secret.txt", is_dir=False)


def test_negation_reinstates_file() -> None:
    engine = IgnoreEngine(builtins=(), gitignore=("*.log", "!keep.log"))
    assert engine.is_ignored("debug.log", is_dir=False)
    assert not engine.is_ignored("keep.log", is_dir=False)


def test_double_star_matches_across_dirs() -> None:
    engine = IgnoreEngine(builtins=(), gitignore=("a/**/z.txt",))
    assert engine.is_ignored("a/z.txt", is_dir=False)
    assert engine.is_ignored("a/b/c/z.txt", is_dir=False)


def test_never_exclude_overrides_ignore() -> None:
    globs = default_language_index().never_exclude_globs
    engine = IgnoreEngine(
        builtins=(),
        gitignore=("*.sql", "*.lock", "Dockerfile"),
        never_exclude_globs=globs,
    )
    # These would be ignored, but the non-exclusion guarantee wins.
    assert not engine.is_ignored("db/schema.sql", is_dir=False)
    assert not engine.is_ignored("uv.lock", is_dir=False)
    assert not engine.is_ignored("Dockerfile", is_dir=False)


def test_comments_and_blanks_ignored() -> None:
    engine = IgnoreEngine(builtins=(), gitignore=("# a comment", "", "  ", "*.tmp"))
    assert engine.is_ignored("x.tmp", is_dir=False)
    assert not engine.is_ignored("x.py", is_dir=False)
