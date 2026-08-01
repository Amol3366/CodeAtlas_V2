"""Ignore-rule precedence and pattern support."""

from __future__ import annotations

from pathlib import Path

from codeatlas.repositories.ignore_rules import IgnoreRules


def test_default_patterns_exclude_build_and_vcs_directories(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored(".git", is_directory=True) is True
    assert rules.is_ignored("node_modules", is_directory=True) is True
    assert rules.is_ignored("src/app.min.js", is_directory=False) is True
    assert rules.is_ignored("src/app.py", is_directory=False) is False


def test_default_patterns_exclude_nested_build_directories(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("packages/web/dist", is_directory=True) is True
    assert rules.is_ignored("src/__pycache__", is_directory=True) is True


def test_lockfiles_and_ci_config_are_never_ignored_by_default(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("uv.lock", is_directory=False) is False
    assert rules.is_ignored("Dockerfile", is_directory=False) is False
    assert rules.is_ignored("migrations/0001_init.sql", is_directory=False) is False


def test_gitignore_patterns_are_applied(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("secrets/\n*.tmp\n", encoding="utf-8")
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("secrets", is_directory=True) is True
    assert rules.is_ignored("notes.tmp", is_directory=False) is True
    assert rules.is_ignored("notes.md", is_directory=False) is False


def test_codeatlasignore_overrides_and_negation_reincludes(tmp_path: Path) -> None:
    (tmp_path / ".codeatlasignore").write_text(
        "docs/\n!docs/keep.md\n", encoding="utf-8"
    )
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("docs/other.md", is_directory=False) is True
    assert rules.is_ignored("docs/keep.md", is_directory=False) is False


def test_root_anchored_pattern_matches_only_at_the_root(tmp_path: Path) -> None:
    # "tools" is deliberately not a built-in default, so this test measures the
    # root anchor rather than an unrelated default pattern.
    (tmp_path / ".codeatlasignore").write_text("/tools\n", encoding="utf-8")
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("tools", is_directory=True) is True
    assert rules.is_ignored("src/tools", is_directory=True) is False


def test_user_patterns_apply_last(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path, user_patterns=("*.py",))
    assert rules.is_ignored("src/app.py", is_directory=False) is True


def test_user_pattern_can_ignore_a_never_ignored_basename(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path, user_patterns=("uv.lock",))
    assert rules.is_ignored("uv.lock", is_directory=False) is True


def test_unsupported_pattern_is_reported_and_not_misapplied(tmp_path: Path) -> None:
    (tmp_path / ".codeatlasignore").write_text("src/**/deep/*.py\n", encoding="utf-8")
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("src/a/deep/x.py", is_directory=False) is False
    assert any("IGNORE_PATTERN_UNSUPPORTED" in warning for warning in rules.warnings)


def test_comments_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    (tmp_path / ".codeatlasignore").write_text(
        "# comment\n\n   \n*.log\n", encoding="utf-8"
    )
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("app.log", is_directory=False) is True
    assert rules.warnings == ()


class TestEnvFiles:
    """Blueprint 8.11 asks for `.env` to be excluded by default.

    Scope, stated so it is not oversold: a `.env` has no parser, so its
    contents were never parsed, chunked, indexed, or embedded. What an
    unignored one does is appear in file-path search results. This is hygiene
    for a design that puts a credential file at a project root.
    """

    def test_env_files_are_ignored_by_default(self, tmp_path: Path) -> None:
        rules = IgnoreRules.load(tmp_path)

        assert rules.is_ignored(".env", is_directory=False) is True
        assert rules.is_ignored(".env.local", is_directory=False) is True
        assert rules.is_ignored("config/.env", is_directory=False) is True
        assert rules.is_ignored("app.env", is_directory=False) is True

    def test_the_example_stays_indexable(self, tmp_path: Path) -> None:
        # It is documentation and holds no secret; a project's `.env.example`
        # is exactly the kind of file impact analysis should see.
        rules = IgnoreRules.load(tmp_path)

        assert rules.is_ignored(".env.example", is_directory=False) is False

    def test_a_repository_can_override(self, tmp_path: Path) -> None:
        (tmp_path / ".codeatlasignore").write_text("!.env\n", encoding="utf-8")

        rules = IgnoreRules.load(tmp_path)

        assert rules.is_ignored(".env", is_directory=False) is False
