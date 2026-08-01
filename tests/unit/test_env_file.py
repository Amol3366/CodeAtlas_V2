"""Reading `.env`, and refusing to read it from anywhere untrusted."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeatlas.settings.env_file import (
    ENV_FILE_VARIABLE,
    LOCAL_MODEL_VARIABLE,
    OPENAI_DIMENSIONS_VARIABLE,
    OPENAI_MODEL_VARIABLE,
    codeatlas_root,
    configured_local_model,
    configured_openai_dimensions,
    configured_openai_model,
    env_file_path,
    load_env_file,
)


def write(tmp_path: Path, text: str) -> Path:
    target = tmp_path / ".env"
    target.write_text(text, encoding="utf-8")
    return target


class TestParsing:
    def test_applies_simple_assignments(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        path = write(tmp_path, "EXAMPLE_KEY=value\n")

        result = load_env_file(path)

        assert os.environ["EXAMPLE_KEY"] == "value"
        assert result.applied == ("EXAMPLE_KEY",)
        assert result.path == path

    def test_ignores_comments_and_blank_lines(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        write(tmp_path, "# a comment\n\n   \nEXAMPLE_KEY=value\n")

        load_env_file(tmp_path / ".env")

        assert os.environ["EXAMPLE_KEY"] == "value"

    def test_accepts_export_prefix(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        write(tmp_path, "export EXAMPLE_KEY=value\n")

        load_env_file(tmp_path / ".env")

        assert os.environ["EXAMPLE_KEY"] == "value"

    def test_strips_matching_quotes_but_keeps_inner_text(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SINGLE", raising=False)
        monkeypatch.delenv("DOUBLE", raising=False)
        write(tmp_path, "SINGLE='a # b'\nDOUBLE=\"c d\"\n")

        load_env_file(tmp_path / ".env")

        # The `#` inside quotes is content, not the start of a comment.
        assert os.environ["SINGLE"] == "a # b"
        assert os.environ["DOUBLE"] == "c d"

    def test_strips_a_trailing_comment_from_an_unquoted_value(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        write(tmp_path, "EXAMPLE_KEY=value   # trailing\n")

        load_env_file(tmp_path / ".env")

        assert os.environ["EXAMPLE_KEY"] == "value"

    def test_keeps_equals_signs_inside_the_value(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        write(tmp_path, "EXAMPLE_KEY=a=b=c\n")

        load_env_file(tmp_path / ".env")

        assert os.environ["EXAMPLE_KEY"] == "a=b=c"

    def test_tolerates_crlf_and_a_byte_order_mark(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        target = tmp_path / ".env"
        target.write_bytes(b"\xef\xbb\xbfEXAMPLE_KEY=value\r\n")

        load_env_file(target)

        assert os.environ["EXAMPLE_KEY"] == "value"

    def test_skips_malformed_lines_without_raising(self, tmp_path, monkeypatch):
        # A broken config line must not stop a deterministic tool from starting.
        monkeypatch.delenv("GOOD_KEY", raising=False)
        write(tmp_path, "not an assignment\n1BAD=x\n=novalue\nGOOD_KEY=good\n")

        result = load_env_file(tmp_path / ".env")

        assert os.environ["GOOD_KEY"] == "good"
        assert result.applied == ("GOOD_KEY",)

    def test_a_missing_file_is_normal(self, tmp_path):
        result = load_env_file(tmp_path / "absent")

        assert result.applied == ()
        assert result.path is None

    def test_an_unreadable_file_is_not_fatal(self, tmp_path):
        # A directory where a file is expected: readable path, unreadable content.
        target = tmp_path / ".env"
        target.mkdir()

        result = load_env_file(target)

        assert result.applied == ()


class TestPrecedence:
    def test_the_real_environment_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EXAMPLE_KEY", "from-shell")
        write(tmp_path, "EXAMPLE_KEY=from-file\n")

        result = load_env_file(tmp_path / ".env")

        assert os.environ["EXAMPLE_KEY"] == "from-shell"
        assert result.applied == ()

    def test_loading_twice_changes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EXAMPLE_KEY", raising=False)
        path = write(tmp_path, "EXAMPLE_KEY=value\n")

        load_env_file(path)
        second = load_env_file(path)

        assert os.environ["EXAMPLE_KEY"] == "value"
        assert second.applied == ()


class TestLocation:
    def test_the_root_is_this_checkout(self):
        root = codeatlas_root()

        assert root is not None
        assert (root / "pyproject.toml").is_file()

    def test_the_override_is_honoured(self, tmp_path, monkeypatch):
        target = tmp_path / "custom.env"
        target.write_text("EXAMPLE_KEY=value\n", encoding="utf-8")
        monkeypatch.setenv(ENV_FILE_VARIABLE, str(target))

        assert env_file_path() == target

    def test_the_working_directory_is_never_searched(self, tmp_path, monkeypatch):
        # The rule this whole design turns on: a repository you index must not
        # be able to configure the tool that indexes it.
        monkeypatch.delenv(ENV_FILE_VARIABLE, raising=False)
        monkeypatch.delenv("HOSTILE_KEY", raising=False)
        (tmp_path / ".env").write_text("HOSTILE_KEY=owned\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        resolved = env_file_path()
        load_env_file()

        assert resolved != tmp_path / ".env"
        assert "HOSTILE_KEY" not in os.environ


class TestConfiguredValues:
    def test_absent_variables_read_as_none(self, monkeypatch):
        for name in (
            OPENAI_MODEL_VARIABLE,
            OPENAI_DIMENSIONS_VARIABLE,
            LOCAL_MODEL_VARIABLE,
        ):
            monkeypatch.delenv(name, raising=False)

        assert configured_openai_model() is None
        assert configured_openai_dimensions() is None
        assert configured_local_model() is None

    def test_blank_and_whitespace_read_as_none(self, monkeypatch):
        monkeypatch.setenv(OPENAI_MODEL_VARIABLE, "   ")

        assert configured_openai_model() is None

    def test_values_are_trimmed(self, monkeypatch):
        monkeypatch.setenv(LOCAL_MODEL_VARIABLE, "  BAAI/bge-small-en-v1.5  ")

        assert configured_local_model() == "BAAI/bge-small-en-v1.5"

    def test_dimensions_parse_as_an_integer(self, monkeypatch):
        monkeypatch.setenv(OPENAI_DIMENSIONS_VARIABLE, "3072")

        assert configured_openai_dimensions() == 3072

    @pytest.mark.parametrize("value", ["abc", "0", "-5", "1536.5"])
    def test_an_unusable_dimension_is_refused(self, monkeypatch, value):
        # Silently falling back to the default would label 3072-wide vectors
        # 1536 — the exact corruption this setting exists to prevent.
        from codeatlas.domain.errors import InvalidRequestError

        monkeypatch.setenv(OPENAI_DIMENSIONS_VARIABLE, value)

        with pytest.raises(InvalidRequestError):
            configured_openai_dimensions()
