# `.env` Provider Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user put `OPENAI_API_KEY` and embedding-model choices in a `.env` file at the CodeAtlas project root, and have both the OpenAI and local providers honour it.

**Architecture:** A new leaf package `codeatlas.settings` reads a `.env` file found at a **fixed** location — the CodeAtlas root resolved from the package's own location, never the current directory — and applies values with `os.environ.setdefault`, so the real environment always wins. Provider construction reads model identity through small helpers instead of hardcoded constants. Nothing here can grant a repository permission to transmit; that stays in SQLite.

**Tech Stack:** Python 3.12, stdlib only (no new runtime dependency), pytest, existing FastAPI/Typer/MCP entry points.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-env-provider-configuration-design.md`. Branch: `env-provider-configuration`.
- **`.env` supplies credentials and model identity, never consent.** No variable added here may cause a repository whose stored policy is `none` to transmit. `build_embedding_provider`'s existing docstring states this rule; do not weaken it.
- Precedence is **real environment > `.env` > pinned default**, implemented with `os.environ.setdefault`. Never `os.environ[key] = value`.
- The `.env` path is `$CODEATLAS_ENV_FILE`, else `<codeatlas-root>/.env`. **The current working directory is never searched.**
- **No new runtime dependency.** The parser is hand-written stdlib. This matches the repo's existing choices (a hand-rolled YAML line scanner; stdlib `tomllib` only).
- Nothing optional is imported at module scope. `settings/env_file.py` must import only `os`, `sys`, `dataclasses`, `pathlib`.
- The credential is never returned, logged, stored, or formatted. The loader returns applied key **names** only.
- Variable names, exactly: `OPENAI_API_KEY`, `CODEATLAS_ENV_FILE`, `CODEATLAS_OPENAI_EMBEDDING_MODEL`, `CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS`, `CODEATLAS_LOCAL_EMBEDDING_MODEL`.
- Use `monkeypatch.setenv` / `monkeypatch.delenv` in every test that touches the environment. A leaked variable breaks unrelated tests in the same session.
- Commit after every task. Conventional-commit subjects, and end each message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Run `uv run pytest`, `uv run ruff check .`, `uv run mypy src` before each commit.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `.gitignore` | **Modify.** Ignore real env files, keep `.env.example`. |
| `.env.example` | **Create.** The committed template a user copies. |
| `src/codeatlas/settings/__init__.py` | **Create.** Package marker; re-exports the public helpers. |
| `src/codeatlas/settings/env_file.py` | **Create.** Find the root, parse `.env`, apply with `setdefault`, expose raw configured values. |
| `src/codeatlas/semantic/providers.py` | **Modify.** Resolve model identity through the helpers; require dimensions for a custom OpenAI model; accept `dimensions` in the constructor. |
| `src/codeatlas/application/settings.py` | **Modify.** `models()` reports configured identity and explains a misconfigured custom model. |
| `src/codeatlas/cli/main.py` | **Modify.** Load `.env` in `main()`. |
| `src/codeatlas/api/app.py` | **Modify.** Load `.env` in `create_app()`. |
| `src/codeatlas/mcp/server.py` | **Modify.** Load `.env` in `main()`. |
| `src/codeatlas/repositories/ignore_rules.py` | **Modify.** Default-ignore env files, re-include `.env.example`. |
| `tests/unit/test_env_file.py` | **Create.** Parsing, precedence, root resolution. |
| `tests/unit/test_embedding_providers.py` | **Modify.** Configured models reach constructors; dimensions rule. |
| `tests/unit/test_ignore_rules.py` | **Modify.** Env files ignored; `.env.example` and `.codeatlasignore` override. |
| `tests/integration/test_settings_service.py` | **Modify.** `models()` reporting. |
| `tests/security/test_env_configuration.py` | **Create.** The seven controls. |
| `docs/adr/0011-configurable-embedding-models.md` | **Create.** Amends ADR-0009 decision 4. |

---

### Task 1: Make it safe to have a `.env` before one exists

**Files:**
- Modify: `.gitignore`
- Create: `.env.example`

**Interfaces:**
- Produces: the documented variable names every later task uses.

This lands first and alone. Until `.gitignore` knows about `.env`, a real key is one `git add -A` from the history.

- [ ] **Step 1: Ignore real env files, keep the template**

Append to `.gitignore`, after the `.claude/` block:

```gitignore
# Provider credentials and model selection. The example is committed; anything
# holding a real value is not. The negation must follow the patterns it
# re-includes — .gitignore takes the last match.
.env
.env.*
*.env
!.env.example
```

- [ ] **Step 2: Verify the rules do what they claim**

```bash
printf 'OPENAI_API_KEY=sk-not-a-real-key\n' > .env
git check-ignore -v .env .env.local
git check-ignore -v .env.example; echo "exit=$? (expect 1 — NOT ignored)"
rm .env
```

Expected: `.env` and `.env.local` report a matching rule; `.env.example` prints nothing and exits 1.

- [ ] **Step 3: Write the template**

Create `.env.example`:

```ini
# CodeAtlas configuration.
#
# Copy this file to `.env` in this same folder and edit it:
#
#     copy .env.example .env
#
# CodeAtlas reads `.env` from its own project folder — not from whatever
# directory you happen to run the command in. That is deliberate: a repository
# you index must never be able to configure the tool that indexes it. To use a
# different file, set CODEATLAS_ENV_FILE to its full path.
#
# A variable already exported in your shell always wins over this file, so you
# can override any of these for a single command without editing anything.
#
# Every setting here is OPTIONAL. With none of them, CodeAtlas runs exactly as
# it does today: deterministic search, no embeddings, nothing leaves the
# machine.


# ---------------------------------------------------------------------------
# OpenAI (optional, and it transmits)
# ---------------------------------------------------------------------------
# Needed only if you switch a repository's embedding provider to "openai" in
# Settings. Setting a key here does NOT enable anything on its own — permission
# is per repository and is granted in the app, never in this file.
#
# Requires: uv sync --extra semantic-openai
OPENAI_API_KEY=sk-your-key-here

# Which OpenAI embedding model to use.
# Default when unset: text-embedding-3-small
# CODEATLAS_OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# How many numbers that model returns per embedding.
# REQUIRED if you change the model above to anything other than the default,
# because the vector index is labelled with this width — a wrong value corrupts
# search results silently. CodeAtlas refuses to embed rather than guess.
#   text-embedding-3-small -> 1536
#   text-embedding-3-large -> 3072
# CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS=1536


# ---------------------------------------------------------------------------
# Local, open-source embeddings (optional, transmits nothing)
# ---------------------------------------------------------------------------
# Any sentence-transformers model. Runs on this machine; no key, no network.
# Default when unset: sentence-transformers/all-MiniLM-L6-v2
#
# Requires: uv sync --extra semantic-local
# CODEATLAS_LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5


# ---------------------------------------------------------------------------
# Storage (optional)
# ---------------------------------------------------------------------------
# Where the local database lives. Unset means the standard per-user location.
# CODEATLAS_DB_PATH=C:\Users\you\AppData\Local\CodeAtlas\data\codeatlas.db
```

- [ ] **Step 4: Confirm the template is tracked and the real file is not**

```bash
git add .env.example .gitignore
git status --short
```

Expected: `.env.example` and `.gitignore` staged; no `.env` present.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: ignore real env files and document every setting

The gitignore rules land before any loader exists, so there is no window in
which a real credential is one `git add -A` away from the history.

.env.example is the file a user copies. It states the two things that surprise
people: this file grants no permission to transmit, and it is read from the
CodeAtlas folder rather than the directory you run the command in.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The `.env` reader

**Files:**
- Create: `src/codeatlas/settings/__init__.py`, `src/codeatlas/settings/env_file.py`
- Test: `tests/unit/test_env_file.py`

**Interfaces:**
- Produces, all imported by later tasks from `codeatlas.settings.env_file`:
  - `ENV_FILE_VARIABLE: str = "CODEATLAS_ENV_FILE"`
  - `OPENAI_MODEL_VARIABLE: str = "CODEATLAS_OPENAI_EMBEDDING_MODEL"`
  - `OPENAI_DIMENSIONS_VARIABLE: str = "CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS"`
  - `LOCAL_MODEL_VARIABLE: str = "CODEATLAS_LOCAL_EMBEDDING_MODEL"`
  - `codeatlas_root() -> Path | None`
  - `env_file_path() -> Path | None`
  - `load_env_file(path: Path | None = None) -> LoadedEnv`
  - `LoadedEnv` frozen dataclass with `path: Path | None` and `applied: tuple[str, ...]`
  - `configured_openai_model() -> str | None`
  - `configured_openai_dimensions() -> int | None`
  - `configured_local_model() -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_env_file.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_env_file.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'codeatlas.settings'`.

- [ ] **Step 3: Create the package marker**

Create `src/codeatlas/settings/__init__.py`:

```python
"""Process-level configuration: where settings come from before a database.

Distinct from `application.settings`, which owns *per-repository* provider
policy stored in SQLite. Nothing in this package grants permission to do
anything; it supplies credentials and model identity only.
"""
```

- [ ] **Step 4: Write the reader**

Create `src/codeatlas/settings/env_file.py`:

```python
"""Reading `.env` from a fixed location beside CodeAtlas itself.

Three rules make this safe enough to load automatically at startup.

**The location is fixed, not discovered.** The file is read from
`$CODEATLAS_ENV_FILE`, or from the CodeAtlas root resolved through the
package's own path — never from the current working directory. A
current-directory search would let a repository you merely *index* configure
the tool that indexes it, which inverts `CLAUDE.md` Section 4.4: repository
content is data, never instructions.

**The real environment always wins.** Values are applied with
`os.environ.setdefault`, so an exported variable outranks the file. A stale
`.env` can never silently beat a deliberate export, and CI needs no special
case.

**Nothing here grants consent.** These variables carry a credential and model
identity. Whether a repository may transmit lives in SQLite, per repository —
see `build_embedding_provider`, which documents that there is deliberately no
environment override for it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from codeatlas.domain.errors import InvalidRequestError

ENV_FILE_VARIABLE = "CODEATLAS_ENV_FILE"
ENV_FILE_NAME = ".env"

OPENAI_MODEL_VARIABLE = "CODEATLAS_OPENAI_EMBEDDING_MODEL"
OPENAI_DIMENSIONS_VARIABLE = "CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS"
LOCAL_MODEL_VARIABLE = "CODEATLAS_LOCAL_EMBEDDING_MODEL"

# Bounds, because this file is read before anything else and a pathological one
# must not become a startup hang. Generous enough that no honest config trips
# them.
_MAX_LINES = 500
_MAX_LINE_LENGTH = 4096
# How far above the package to look for the project marker. The layout is
# `<root>/src/codeatlas/settings/env_file.py`, so the root is four parents up;
# the bound stops a stray `pyproject.toml` far up the tree being adopted.
_MAX_ROOT_DEPTH = 6


@dataclass(frozen=True)
class LoadedEnv:
    """What one load did.

    ``applied`` carries key **names only**. A value here would eventually reach
    a log line, a `repr`, or a diagnostic bundle, and one of those values is an
    API key.
    """

    path: Path | None
    applied: tuple[str, ...]


def codeatlas_root() -> Path | None:
    """The folder CodeAtlas itself lives in, or ``None`` if it has none.

    Frozen builds answer with the folder holding the executable — PyInstaller
    onedir puts `codeatlas.exe` at the top of the shipped tree. A source
    checkout answers with the folder holding `pyproject.toml`.

    ``None`` is a real answer: a wheel installed into site-packages has no
    project root, and inventing one would point at site-packages. Those
    installations configure through ``CODEATLAS_ENV_FILE``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    here = Path(__file__).resolve()
    for candidate in here.parents[:_MAX_ROOT_DEPTH]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def env_file_path() -> Path | None:
    """Where `.env` would be read from, whether or not it exists."""
    override = os.environ.get(ENV_FILE_VARIABLE, "").strip()
    if override:
        return Path(override)
    root = codeatlas_root()
    return None if root is None else root / ENV_FILE_NAME


def parse_env_text(text: str) -> dict[str, str]:
    """Parse `KEY=VALUE` lines, skipping anything unusable.

    Skipping rather than raising is deliberate: a typo in an optional config
    file must not stop a tool whose whole value proposition is working
    deterministically without one.
    """
    values: dict[str, str] = {}
    for line in text.lstrip("\ufeff").splitlines()[:_MAX_LINES]:
        entry = _parse_line(line)
        if entry is not None:
            values[entry[0]] = entry[1]
    return values


def load_env_file(path: Path | None = None) -> LoadedEnv:
    """Apply `.env` values the real environment has not already set."""
    target = path if path is not None else env_file_path()
    if target is None:
        return LoadedEnv(path=None, applied=())
    try:
        text = target.read_text(encoding="utf-8-sig")
    except OSError:
        # Missing is the normal case and needs no warning. Unreadable is rarer
        # and equally non-fatal: deterministic operation needs no settings.
        return LoadedEnv(path=None, applied=())

    applied: list[str] = []
    for key, value in parse_env_text(text).items():
        if key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return LoadedEnv(path=target, applied=tuple(applied))


def configured_openai_model() -> str | None:
    """The configured OpenAI embedding model, or ``None`` for the default."""
    return _text(OPENAI_MODEL_VARIABLE)


def configured_local_model() -> str | None:
    """The configured local embedding model, or ``None`` for the default."""
    return _text(LOCAL_MODEL_VARIABLE)


def configured_openai_dimensions() -> int | None:
    """The configured vector width, or ``None`` when unset.

    Refuses anything that is not a positive integer. Falling back to the
    default on a typo would label vectors with a width they do not have, which
    is precisely the silent corruption this setting exists to prevent.
    """
    raw = _text(OPENAI_DIMENSIONS_VARIABLE)
    if raw is None:
        return None
    try:
        width = int(raw)
    except ValueError:
        width = 0
    if width <= 0:
        raise InvalidRequestError(
            f"{OPENAI_DIMENSIONS_VARIABLE} must be a positive whole number.",
            details={"variable": OPENAI_DIMENSIONS_VARIABLE},
        )
    return width


def _text(variable: str) -> str | None:
    value = os.environ.get(variable, "").strip()
    return value or None


def _parse_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or len(line) > _MAX_LINE_LENGTH:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None

    key, _, raw = stripped.partition("=")
    key = key.strip()
    if not key.isidentifier():
        return None
    return key, _parse_value(raw.strip())


def _parse_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        # Quoted: everything between the quotes is content, including a `#`.
        return raw[1:-1]
    # Unquoted: a `#` preceded by whitespace starts a trailing comment.
    marker = raw.find(" #")
    return (raw[:marker] if marker >= 0 else raw).strip()


__all__ = [
    "ENV_FILE_NAME",
    "ENV_FILE_VARIABLE",
    "LOCAL_MODEL_VARIABLE",
    "OPENAI_DIMENSIONS_VARIABLE",
    "OPENAI_MODEL_VARIABLE",
    "LoadedEnv",
    "codeatlas_root",
    "configured_local_model",
    "configured_openai_dimensions",
    "configured_openai_model",
    "env_file_path",
    "load_env_file",
    "parse_env_text",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_env_file.py -q`
Expected: PASS, 20 tests.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check . && uv run mypy src`
Expected: both exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/settings tests/unit/test_env_file.py
git commit -m "$(cat <<'EOF'
feat: read .env from a fixed location beside CodeAtlas

The location is fixed rather than discovered. Reading .env from the current
directory would let a repository you merely index configure the tool that
indexes it, which inverts the rule that repository content is data and never
instructions — so the file is read from the CodeAtlas root or from an explicit
CODEATLAS_ENV_FILE, and a test proves a planted .env in the working directory
is ignored.

Values are applied with setdefault, so an exported variable always outranks the
file. A malformed line is skipped rather than raised: a typo in an optional
config file must not stop a tool that works without one.

The result carries key names, never values.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Load it at every entry point

**Files:**
- Modify: `src/codeatlas/cli/main.py` (the `main()` function near line 1215)
- Modify: `src/codeatlas/api/app.py` (`create_app()`, near line 77)
- Modify: `src/codeatlas/mcp/server.py` (the `main()` function near line 144)
- Test: `tests/unit/test_env_file.py` (extend)

**Interfaces:**
- Consumes: `load_env_file()` from Task 2.
- Produces: `OPENAI_API_KEY` present in `os.environ` before `describe_available_providers()` runs, which is what makes the settings surface offer OpenAI.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_env_file.py`:

```python
class TestEntryPoints:
    def test_creating_the_app_loads_the_env_file(self, tmp_path, monkeypatch):
        # The payoff: a key in `.env` reaches the code that decides whether the
        # settings page may offer OpenAI, with no shell export.
        from codeatlas.api.app import create_app

        monkeypatch.delenv("EXAMPLE_APP_KEY", raising=False)
        env = tmp_path / "custom.env"
        env.write_text("EXAMPLE_APP_KEY=loaded\n", encoding="utf-8")
        monkeypatch.setenv(ENV_FILE_VARIABLE, str(env))

        create_app(tmp_path / "codeatlas.db", watch=False)

        assert os.environ["EXAMPLE_APP_KEY"] == "loaded"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_env_file.py::TestEntryPoints -q`
Expected: FAIL with `KeyError: 'EXAMPLE_APP_KEY'`.

- [ ] **Step 3: Load in the API factory**

In `src/codeatlas/api/app.py`, add the import beside the other `codeatlas` imports:

```python
from codeatlas.settings.env_file import load_env_file
```

and make it the first statement in `create_app`'s body, immediately after the
docstring and before `resolved_path` is computed:

```python
    # Before anything reads the environment. `describe_available_providers`
    # decides whether the settings surface may offer OpenAI by looking for
    # OPENAI_API_KEY, and it must see what `.env` supplies. Idempotent, so a
    # process that also ran the CLI loses nothing.
    load_env_file()
```

- [ ] **Step 4: Load in the CLI entry point**

In `src/codeatlas/cli/main.py`, add the import beside the other `codeatlas`
imports, then make it the first statement of `main()`:

```python
def main() -> None:
    """Console-script entry point."""
    # Deliberately here and not in `app()`. Tests invoke the Typer app directly
    # and must not pick up a developer's real `.env`; the console script is the
    # thing a user runs.
    load_env_file()
    try:
        app()
    except sqlite3.Error:
        typer.echo("INTERNAL_ERROR: the local database could not be used.", err=True)
        raise typer.Exit(EXIT_INTERNAL_FAILURE) from None
```

- [ ] **Step 5: Load in the MCP entry point**

In `src/codeatlas/mcp/server.py`, add the import and make it the first
statement of `main()`:

```python
def main() -> None:  # pragma: no cover
    load_env_file()
    run_stdio()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_env_file.py -q`
Expected: PASS, 21 tests.

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. This is the run that would catch a `.env` in the checkout
leaking into unrelated tests — there is none, and `create_app` is the only
loader a test reaches.

- [ ] **Step 8: Commit**

```bash
git add src/codeatlas/api/app.py src/codeatlas/cli/main.py src/codeatlas/mcp/server.py tests/unit/test_env_file.py
git commit -m "$(cat <<'EOF'
feat: load .env at the CLI, API, and MCP entry points

Loading happens before anything reads the environment, because
describe_available_providers decides whether the settings surface may offer
OpenAI by looking for OPENAI_API_KEY — that is the visible payoff of the whole
change.

The CLI loads in main() rather than in app(), so tests that invoke the Typer
app directly cannot pick up a developer's real .env.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Configurable models, and a refusal instead of a corrupt index

**Files:**
- Modify: `src/codeatlas/semantic/providers.py`
- Modify: `src/codeatlas/application/settings.py` (`models()`, near line 172)
- Test: `tests/unit/test_embedding_providers.py`, `tests/integration/test_settings_service.py`

**Interfaces:**
- Consumes: `configured_openai_model()`, `configured_openai_dimensions()`, `configured_local_model()` from Task 2.
- Produces, in `codeatlas.semantic.providers`:
  - `resolve_openai_embedding_model() -> tuple[str, int]` — model ID and vector width; raises `ProviderUnavailableError` when a custom model has no width.
  - `resolve_local_embedding_model() -> str`
  - `OpenAIEmbeddingProvider.__init__` gains `dimensions: int | None = None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_embedding_providers.py`:

```python
class TestConfiguredModels:
    """Model identity comes from configuration; a wrong width is refused."""

    def test_the_default_model_needs_no_dimensions(self, monkeypatch):
        from codeatlas.semantic.providers import (
            OPENAI_DIMENSIONS,
            OPENAI_MODEL_ID,
            resolve_openai_embedding_model,
        )
        from codeatlas.settings.env_file import (
            OPENAI_DIMENSIONS_VARIABLE,
            OPENAI_MODEL_VARIABLE,
        )

        monkeypatch.delenv(OPENAI_MODEL_VARIABLE, raising=False)
        monkeypatch.delenv(OPENAI_DIMENSIONS_VARIABLE, raising=False)

        assert resolve_openai_embedding_model() == (OPENAI_MODEL_ID, OPENAI_DIMENSIONS)

    def test_a_custom_model_with_its_width_is_accepted(self, monkeypatch):
        from codeatlas.semantic.providers import resolve_openai_embedding_model
        from codeatlas.settings.env_file import (
            OPENAI_DIMENSIONS_VARIABLE,
            OPENAI_MODEL_VARIABLE,
        )

        monkeypatch.setenv(OPENAI_MODEL_VARIABLE, "text-embedding-3-large")
        monkeypatch.setenv(OPENAI_DIMENSIONS_VARIABLE, "3072")

        assert resolve_openai_embedding_model() == ("text-embedding-3-large", 3072)

    def test_a_custom_model_without_its_width_is_refused(self, monkeypatch):
        # The whole point. 3072-wide vectors in a namespace labelled 1536 is a
        # corrupted similarity space that reports nothing and is found months
        # later as poor results.
        from codeatlas.domain.errors import ProviderUnavailableError
        from codeatlas.semantic.providers import resolve_openai_embedding_model
        from codeatlas.settings.env_file import (
            OPENAI_DIMENSIONS_VARIABLE,
            OPENAI_MODEL_VARIABLE,
        )

        monkeypatch.setenv(OPENAI_MODEL_VARIABLE, "text-embedding-3-large")
        monkeypatch.delenv(OPENAI_DIMENSIONS_VARIABLE, raising=False)

        with pytest.raises(ProviderUnavailableError) as raised:
            resolve_openai_embedding_model()

        # The message must name the variable to set, not merely complain.
        assert OPENAI_DIMENSIONS_VARIABLE in str(raised.value)

    def test_a_width_disagreeing_with_the_default_model_is_refused(self, monkeypatch):
        # CodeAtlas does not send OpenAI's `dimensions` request parameter, so a
        # width that disagrees with the default model would be a label, not a
        # request — the same corruption by another route.
        from codeatlas.domain.errors import ProviderUnavailableError
        from codeatlas.semantic.providers import resolve_openai_embedding_model
        from codeatlas.settings.env_file import (
            OPENAI_DIMENSIONS_VARIABLE,
            OPENAI_MODEL_VARIABLE,
        )

        monkeypatch.delenv(OPENAI_MODEL_VARIABLE, raising=False)
        monkeypatch.setenv(OPENAI_DIMENSIONS_VARIABLE, "512")

        with pytest.raises(ProviderUnavailableError):
            resolve_openai_embedding_model()

    def test_the_provider_reports_the_configured_identity(self, monkeypatch):
        from codeatlas.semantic.providers import OpenAIEmbeddingProvider

        class FakeClient:
            embeddings = None

        provider = OpenAIEmbeddingProvider(
            client=FakeClient(), model_id="text-embedding-3-large", dimensions=3072
        )

        assert provider.model_id == "text-embedding-3-large"
        assert provider.dimensions == 3072

    def test_the_local_model_comes_from_configuration(self, monkeypatch):
        from codeatlas.semantic.providers import (
            LOCAL_MODEL_ID,
            resolve_local_embedding_model,
        )
        from codeatlas.settings.env_file import LOCAL_MODEL_VARIABLE

        monkeypatch.delenv(LOCAL_MODEL_VARIABLE, raising=False)
        assert resolve_local_embedding_model() == LOCAL_MODEL_ID

        monkeypatch.setenv(LOCAL_MODEL_VARIABLE, "BAAI/bge-small-en-v1.5")
        assert resolve_local_embedding_model() == "BAAI/bge-small-en-v1.5"
```

Ensure `import pytest` is present at the top of that file.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_embedding_providers.py::TestConfiguredModels -q`
Expected: FAIL with `ImportError: cannot import name 'resolve_openai_embedding_model'`.

- [ ] **Step 3: Add the resolvers**

In `src/codeatlas/semantic/providers.py`, add the import at the top:

```python
from codeatlas.settings.env_file import (
    OPENAI_DIMENSIONS_VARIABLE,
    OPENAI_MODEL_VARIABLE,
    configured_local_model,
    configured_openai_dimensions,
    configured_openai_model,
)
```

and add both resolvers immediately after the `OPENAI_API_KEY_VARIABLE`
constant:

```python
def resolve_local_embedding_model() -> str:
    """Which sentence-transformers model the local provider loads.

    Safe to configure freely: the provider reads the true width from the model
    it loaded, and the namespace is derived from that. A different model simply
    means a different namespace.
    """
    return configured_local_model() or LOCAL_MODEL_ID


def resolve_openai_embedding_model() -> tuple[str, int]:
    """The configured OpenAI model and the width its vectors will have.

    The width cannot be discovered for free — asking OpenAI costs a billable
    call per construction — so a non-default model must declare it. Refusing is
    the only safe answer: `embedding_namespace_id` labels the namespace with
    this number, and a wrong label puts vectors of one width into a space
    describing another. That never raises; it just returns worse results,
    indefinitely.
    """
    model = configured_openai_model()
    width = configured_openai_dimensions()

    if model is None or model == OPENAI_MODEL_ID:
        if width is not None and width != OPENAI_DIMENSIONS:
            raise ProviderUnavailableError(
                f"{OPENAI_DIMENSIONS_VARIABLE} is {width}, but "
                f"{OPENAI_MODEL_ID} returns {OPENAI_DIMENSIONS}. CodeAtlas does "
                "not request shortened embeddings, so the two must agree.",
                details={
                    "provider": EmbeddingProviderKind.OPENAI.value,
                    "variable": OPENAI_DIMENSIONS_VARIABLE,
                },
            )
        return OPENAI_MODEL_ID, OPENAI_DIMENSIONS

    if width is None:
        raise ProviderUnavailableError(
            f"{OPENAI_MODEL_VARIABLE} is set to '{model}', so "
            f"{OPENAI_DIMENSIONS_VARIABLE} must also be set — CodeAtlas labels "
            "its vector index with that width and will not guess it. "
            "text-embedding-3-large is 3072.",
            details={
                "provider": EmbeddingProviderKind.OPENAI.value,
                "variable": OPENAI_DIMENSIONS_VARIABLE,
            },
        )
    return model, width
```

- [ ] **Step 4: Let the provider carry a configured width**

In `OpenAIEmbeddingProvider.__init__`, add the parameter and assign it. Replace
the signature and the first two body lines:

```python
    def __init__(
        self,
        *,
        model_id: str = OPENAI_MODEL_ID,
        dimensions: int | None = None,
        client: object | None = None,
        timeout: float = OPENAI_TIMEOUT_SECONDS,
    ) -> None:
        self.model_id = model_id
        # Instance-level, because the class attribute describes the pinned
        # model only. The namespace is built from this number.
        self.dimensions = OPENAI_DIMENSIONS if dimensions is None else dimensions
        if client is not None:
            self._client = client
            return
```

- [ ] **Step 5: Use the resolvers when building**

In `ProviderFactory.build`, replace the `GovernedEmbeddingProvider` construction:

```python
        client = self._open_client() if self._open_client is not None else None
        model_id, dimensions = resolve_openai_embedding_model()
        return GovernedEmbeddingProvider(
            inner=OpenAIEmbeddingProvider(
                client=client, model_id=model_id, dimensions=dimensions
            ),
            policy=policy,
            connection=self._connection,  # type: ignore[arg-type]
        )
```

In `build_embedding_provider`, replace the local branch:

```python
    if kind is EmbeddingProviderKind.LOCAL:
        return _cached_local_provider(resolve_local_embedding_model())
```

- [ ] **Step 6: Report configured identity in the settings surface**

In `src/codeatlas/application/settings.py`, inside `models()`, replace the
import block and the two model descriptors. The import gains the resolvers:

```python
        from codeatlas.semantic.providers import (
            LOCAL_MODEL_DIMENSIONS,
            LOCAL_MODEL_ID,
            OPENAI_API_KEY_VARIABLE,
            describe_available_providers,
            resolve_local_embedding_model,
            resolve_openai_embedding_model,
        )
        from codeatlas.domain.errors import CodeAtlasError

        available = describe_available_providers()
        local_model = resolve_local_embedding_model()
        try:
            openai_model, openai_dimensions = resolve_openai_embedding_model()
            openai_requires: str | None = None
        except CodeAtlasError as error:
            # A misconfigured custom model is reported the same way a missing
            # extra is: the option stays visible and explains itself, rather
            # than disappearing or crashing the settings page.
            openai_model, openai_dimensions = None, None
            openai_requires = error.message
```

then the two descriptors become:

```python
            ModelDescriptor(
                provider=EmbeddingProviderKind.LOCAL,
                model_id=local_model,
                # Known only for the pinned model. Loading a custom one to
                # measure it is exactly the cost this function avoids.
                dimensions=(
                    LOCAL_MODEL_DIMENSIONS if local_model == LOCAL_MODEL_ID else None
                ),
                available=available[EmbeddingProviderKind.LOCAL],
                transmits_off_machine=False,
                requires=(
                    None
                    if available[EmbeddingProviderKind.LOCAL]
                    else "extra:semantic-local"
                ),
            ),
            ModelDescriptor(
                provider=EmbeddingProviderKind.OPENAI,
                model_id=openai_model,
                dimensions=openai_dimensions,
                available=(
                    available[EmbeddingProviderKind.OPENAI]
                    and openai_requires is None
                ),
                transmits_off_machine=True,
                requires=(
                    openai_requires
                    if openai_requires is not None
                    else (
                        None
                        if available[EmbeddingProviderKind.OPENAI]
                        else f"extra:semantic-openai and {OPENAI_API_KEY_VARIABLE}"
                    )
                ),
            ),
```

- [ ] **Step 7: Test the settings surface**

Append to `tests/integration/test_settings_service.py`:

```python
def test_models_report_the_configured_local_model(connection, monkeypatch):
    from codeatlas.application.settings import SettingsService
    from codeatlas.domain.semantic import EmbeddingProviderKind
    from codeatlas.settings.env_file import LOCAL_MODEL_VARIABLE

    monkeypatch.setenv(LOCAL_MODEL_VARIABLE, "BAAI/bge-small-en-v1.5")

    models = SettingsService(connection).models()
    local = next(m for m in models if m.provider is EmbeddingProviderKind.LOCAL)

    assert local.model_id == "BAAI/bge-small-en-v1.5"
    # Unknown until the model loads, and loading it to render a form is what
    # this function exists to avoid.
    assert local.dimensions is None


def test_models_explain_a_custom_openai_model_missing_its_width(
    connection, monkeypatch
):
    from codeatlas.application.settings import SettingsService
    from codeatlas.domain.semantic import EmbeddingProviderKind
    from codeatlas.settings.env_file import (
        OPENAI_DIMENSIONS_VARIABLE,
        OPENAI_MODEL_VARIABLE,
    )

    monkeypatch.setenv(OPENAI_MODEL_VARIABLE, "text-embedding-3-large")
    monkeypatch.delenv(OPENAI_DIMENSIONS_VARIABLE, raising=False)

    models = SettingsService(connection).models()
    openai = next(m for m in models if m.provider is EmbeddingProviderKind.OPENAI)

    assert openai.available is False
    assert openai.requires is not None
    assert OPENAI_DIMENSIONS_VARIABLE in openai.requires
```

Match the existing fixture name in that file for the SQLite connection; if it
differs from `connection`, use the file's own fixture.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/unit/test_embedding_providers.py tests/integration/test_settings_service.py -q`
Expected: PASS.

- [ ] **Step 9: Run the whole suite, lint, and types**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`
Expected: all exit 0.

- [ ] **Step 10: Commit**

```bash
git add src/codeatlas/semantic/providers.py src/codeatlas/application/settings.py tests/unit/test_embedding_providers.py tests/integration/test_settings_service.py
git commit -m "$(cat <<'EOF'
feat: choose embedding models through configuration

Both providers already accepted a model_id and nothing passed one. They now
read it from the environment, which .env supplies.

A custom OpenAI model must declare its vector width. The namespace is labelled
with that number, so a wrong one puts 3072-wide vectors into a space describing
1536 — a corruption that never raises and surfaces months later as poor
results. CodeAtlas refuses to embed and names the variable to set. The local
provider needs no such setting: it reads the true width from the model it
loaded, which costs nothing.

The settings surface reports configured identity, and explains a misconfigured
model the same way it explains a missing extra.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Keep env files out of repository scans

**Files:**
- Modify: `src/codeatlas/repositories/ignore_rules.py:21-46`
- Test: `tests/unit/test_ignore_rules.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks consume.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ignore_rules.py`:

```python
class TestEnvFiles:
    """Blueprint 8.11 asks for `.env` to be excluded by default.

    Scope, stated so it is not oversold: a `.env` has no parser, so its
    contents were never parsed, chunked, indexed, or embedded. What an
    unignored one does is appear in file-path search results. This is hygiene
    for a design that puts a credential file at a project root.
    """

    def test_env_files_are_ignored_by_default(self, tmp_path):
        rules = IgnoreRules.load(tmp_path)

        assert rules.is_ignored(".env", is_directory=False)
        assert rules.is_ignored(".env.local", is_directory=False)
        assert rules.is_ignored("config/.env", is_directory=False)
        assert rules.is_ignored("app.env", is_directory=False)

    def test_the_example_stays_indexable(self, tmp_path):
        # It is documentation and holds no secret; a project's `.env.example`
        # is exactly the kind of file impact analysis should see.
        rules = IgnoreRules.load(tmp_path)

        assert not rules.is_ignored(".env.example", is_directory=False)

    def test_a_repository_can_override(self, tmp_path):
        (tmp_path / ".codeatlasignore").write_text("!.env\n", encoding="utf-8")

        rules = IgnoreRules.load(tmp_path)

        assert not rules.is_ignored(".env", is_directory=False)
```

Match the existing call signature in that file — if the tests there call
`rules.is_ignored(path)` without `is_directory`, drop the keyword.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_ignore_rules.py::TestEnvFiles -q`
Expected: FAIL — `.env` is not ignored.

- [ ] **Step 3: Add the patterns**

In `src/codeatlas/repositories/ignore_rules.py`, extend
`DEFAULT_IGNORE_PATTERNS`, appending after `"*.map"`:

```python
    # Credential files. Blueprint 8.11 names excluding `.env` by default as a
    # required control. The negation must come last: within one precedence
    # group the final matching pattern decides, which is what lets the example
    # — documentation, no secret — stay indexable.
    ".env",
    ".env.*",
    "*.env",
    "!.env.example",
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_ignore_rules.py -q`
Expected: PASS.

- [ ] **Step 5: Confirm no fixture repository silently lost a file**

Run: `uv run pytest -q`
Expected: PASS. Evaluation fixtures contain no `.env`, so no corpus count
should move; a failure here means one did and the plan is wrong about it.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/repositories/ignore_rules.py tests/unit/test_ignore_rules.py
git commit -m "$(cat <<'EOF'
feat: exclude env files from repository scans by default

Blueprint 8.11 names this as a required control and nothing implemented it.

Stated precisely rather than oversold: a .env has no parser, so its contents
were never parsed, chunked, written to FTS, or embedded. What an unignored one
did was appear in file-path search results. This is hygiene for a design that
asks users to keep a credential file at a project root.

.env.example stays indexable — it is documentation — and .codeatlasignore can
still override the default.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The security sweep, the ADR, and the gate

**Files:**
- Create: `tests/security/test_env_configuration.py`
- Create: `docs/adr/0011-configurable-embedding-models.md`
- Modify: `docs/adr/README.md`, `docs/operations/semantic-search.md`, `docs/security/threat-model.md`, `docs/plans/PLAN.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5.

- [ ] **Step 1: Write the security tests**

Create `tests/security/test_env_configuration.py`:

```python
"""What `.env` must never do.

The credential is the asset. These assert the boundaries rather than the
feature: that configuration cannot become consent, that a repository cannot
become configuration, and that the key never leaves the process it was read
into.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.container import build_services
from codeatlas.domain.semantic import EmbeddingProviderKind
from codeatlas.semantic.providers import (
    OPENAI_API_KEY_VARIABLE,
    NoEmbeddingProvider,
    build_embedding_provider,
)
from codeatlas.settings.env_file import (
    ENV_FILE_VARIABLE,
    LOCAL_MODEL_VARIABLE,
    load_env_file,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SECRET = "sk-" + "test-not-a-real-key-abcdef0123456789"


def _write_env(directory: Path, body: str) -> Path:
    target = directory / ".env"
    target.write_text(body, encoding="utf-8")
    return target


def test_configuration_cannot_become_consent(tmp_path, monkeypatch):
    """Every variable set, policy untouched: still no provider."""
    monkeypatch.setenv(OPENAI_API_KEY_VARIABLE, SECRET)
    monkeypatch.setenv(LOCAL_MODEL_VARIABLE, "BAAI/bge-small-en-v1.5")

    database = tmp_path / "codeatlas.db"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(tmp_path), display_name="fixture")
        )
        policy = services.settings.get(repository.repository_id)

    assert policy.embedding_provider is EmbeddingProviderKind.NONE

    from codeatlas.domain.semantic import ProviderPolicy

    provider = build_embedding_provider(
        ProviderPolicy(
            repository_id=repository.repository_id,
            embedding_provider=EmbeddingProviderKind.NONE,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=policy.updated_at,
        )
    )
    assert isinstance(provider, NoEmbeddingProvider)


def test_a_repository_cannot_supply_configuration(tmp_path, monkeypatch):
    """A hostile `.env` in the directory you run from is not read."""
    monkeypatch.delenv(ENV_FILE_VARIABLE, raising=False)
    monkeypatch.delenv("HOSTILE_SETTING", raising=False)
    _write_env(tmp_path, "HOSTILE_SETTING=owned\n")
    monkeypatch.chdir(tmp_path)

    load_env_file()

    assert "HOSTILE_SETTING" not in os.environ


def test_the_credential_is_absent_from_every_response(tmp_path, monkeypatch):
    monkeypatch.setenv(OPENAI_API_KEY_VARIABLE, SECRET)
    database = tmp_path / "codeatlas.db"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(tmp_path), display_name="fixture")
        )

    app = create_app(database, watch=False)
    with TestClient(app) as client:
        bodies = [
            client.get(
                f"/v1/settings?repository_id={repository.repository_id}"
            ).text,
            client.get("/v1/models").text,
            client.get(
                f"/v1/repositories/{repository.repository_id}/diagnostics"
            ).text,
            client.get("/v1/settings").text,  # missing parameter: error envelope
        ]

    for body in bodies:
        assert SECRET not in body
        # The tail alone would be enough to confirm a guess.
        assert SECRET[-12:] not in body


def test_the_loader_returns_names_and_never_values(tmp_path, monkeypatch):
    monkeypatch.delenv("EXAMPLE_SECRET", raising=False)
    path = _write_env(tmp_path, f"EXAMPLE_SECRET={SECRET}\n")

    result = load_env_file(path)

    assert result.applied == ("EXAMPLE_SECRET",)
    assert SECRET not in repr(result)


def test_a_hostile_file_cannot_deny_service(tmp_path):
    body = "\n".join(
        [
            "A" * 20_000,
            "NO_EQUALS_SIGN",
            "=leading",
            "'unterminated=quote",
            *[f"KEY_{index}=value" for index in range(2_000)],
        ]
    )
    path = _write_env(tmp_path, body)

    result = load_env_file(path)

    # Bounded, and it returned rather than raising.
    assert len(result.applied) <= 500


def test_binary_content_is_not_fatal(tmp_path):
    target = tmp_path / ".env"
    target.write_bytes(bytes(range(256)) * 16)

    assert load_env_file(target).applied == ()


def test_env_files_are_not_scanned(tmp_path):
    from codeatlas.repositories.ignore_rules import IgnoreRules
    from codeatlas.repositories.scanner import RepositoryScanner

    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = RepositoryScanner().scan(tmp_path, IgnoreRules.load(tmp_path))

    scanned = {record.relative_path for record in result.files}
    assert "main.py" in scanned
    assert ".env" not in scanned
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/security/test_env_configuration.py -q`
Expected: PASS, 7 tests. If the `ProviderPolicy` constructor signature differs,
read `src/codeatlas/domain/semantic.py` and match it — do not change the
production type to fit the test.

- [ ] **Step 3: Write ADR-0011**

Create `docs/adr/0011-configurable-embedding-models.md`, following the shape of
`docs/adr/0010-repository-scoped-embedding-namespaces.md`. It must record:

- **Context:** ADR-0009 decision 4 pinned `LOCAL_MODEL_ID` and `OPENAI_MODEL_ID`
  because the model ID is recorded on every embedding record and changing it
  changes the similarity space. That reasoning was about *silent* change — an
  upstream default moving underneath the product.
- **Decision:** model identity becomes configurable through the environment,
  supplied by a `.env` file at the CodeAtlas root. The pinned values remain the
  defaults.
- **Why this is safe:** `embedding_namespace_id` derives the namespace from
  `(model_id, dimensions, normalization_version)`, so a configured change
  creates a *new* namespace rather than polluting the existing one, and the
  shadow-migration machinery from P7-09 already moves a repository between
  namespaces with rollback. The hazard ADR-0009 guarded against was an
  identity that changed without the namespace changing; that cannot happen
  here.
- **The one place it is not free:** OpenAI's vector width cannot be discovered
  without a billable call, so a non-default model must declare
  `CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS`, and construction refuses without it.
- **Consequences:** `.env` never grants consent; the current directory is never
  searched; `.env` joins the default ignore patterns as blueprint 8.11
  conformance, explicitly *not* as a leak fix, because a `.env` has no parser
  and its contents were never indexed.
- **Status:** accepted, 2026-08-01. Does not supersede ADR-0009; it amends
  decision 4 and says so.

Add the row to `docs/adr/README.md`'s accepted table:

```markdown
| [0011](0011-configurable-embedding-models.md) | Embedding model identity is configurable through `.env`; namespace derivation keeps it safe, and a custom OpenAI model must declare its width | 7 (post-gate) |
```

- [ ] **Step 4: Update the operations and security docs**

In `docs/operations/semantic-search.md`, add a "Configuring a provider" section:
where `.env` lives and how it is found, the four variables with their defaults,
the precedence rule, that a custom OpenAI model needs its width and why, and
that `.env` grants no permission — the per-repository switch does.

In `docs/security/threat-model.md`, add rows to the Phase 7 enforcement table:
credential supplied by `.env` never appears in a response (naming
`tests/security/test_env_configuration.py`); the working directory is never
searched for `.env`; env files are excluded from scans by default.

- [ ] **Step 5: Run the gate**

Run:

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

Expected: all exit 0. Record actual exit codes; if the gate fails, fix the
cause rather than recording a pass.

- [ ] **Step 6: Append the PLAN handoff**

Append an entry at the top of the Handoff Log in `docs/plans/PLAN.md`,
following the Handoff Schema: UTC timestamp and agent label; transition (none —
Phase 7 stays `complete`, this is post-gate work); outcome and user-visible
behavior; files created and changed; contracts and migrations (none — no schema
change, no REST contract change); the exact verification commands with exit
codes; limitations — specifically that the semantic extras are not installed so
both providers are exercised through fakes and import-failure paths, and that
OpenAI-compatible base URLs and LLM answer generation remain out of scope with
their reasons; and the next required decision (none). Do not modify any
existing entry.

- [ ] **Step 7: Commit**

```bash
git add tests/security/test_env_configuration.py docs/adr docs/operations/semantic-search.md docs/security/threat-model.md docs/plans/PLAN.md
git commit -m "$(cat <<'EOF'
docs: ADR-0011 and the security sweep for .env configuration

ADR-0009 pinned the model IDs against an upstream default moving underneath the
product. Configuring them deliberately is a different thing, and safe for a
specific reason: the namespace is derived from model identity, so a change
creates a new namespace rather than polluting the old one, and shadow migration
already moves between them. ADR-0011 records that rather than editing ADR-0009.

The security tests assert the boundaries rather than the feature: configuration
cannot become consent, a repository cannot become configuration, and the
credential appears in no response, no repr, and no scan.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task. The variables and
`.env.example` → Task 1. The reader, root resolution, precedence, and the
"current directory is never searched" rule → Task 2. Entry-point loading →
Task 3. Configurable models, the dimensions rule, and the settings surface →
Task 4. The ignore patterns (spec decision 7) → Task 5. The seven security
controls, ADR-0011, docs, and the gate → Task 6. Acceptance criteria 1–9 are
covered by Tasks 3, 2, 4, 4, 2, 6, 6, 1, and 6 respectively; criterion 5a by
Task 5.

**Placeholder scan.** No TBD/TODO. Every code step carries literal code. Task 6
steps 3, 4, and 6 describe document content rather than quoting whole files,
which is the right granularity for prose, and each names the specific facts the
document must record.

**Type consistency.** `LoadedEnv(path, applied)` is defined in Task 2 and used
in Tasks 3 and 6. `resolve_openai_embedding_model() -> tuple[str, int]` and
`resolve_local_embedding_model() -> str` are defined in Task 4 and used by
`ProviderFactory.build`, `build_embedding_provider`, and
`SettingsService.models()` in the same task. Variable-name constants are
defined once in Task 2 and imported everywhere else — no literal string
duplicates the constants. `ModelDescriptor.model_id` and `.dimensions` are
already `str | None` and `int | None`, so Task 4's `None` values need no
contract change.

One inconsistency was found and fixed inline: Task 6's security test imported
`OPENAI_API_KEY_VARIABLE` from `codeatlas.settings.env_file`, where it does not
live. It is defined in `codeatlas.semantic.providers` and is imported from
there. The new package deliberately does **not** re-export it — the credential's
variable name belongs with the provider that reads it.

**Two things flagged for the implementer.** Task 4 step 7 and Task 5 step 1
both depend on an existing test file's local conventions (a fixture name, a
method signature); each says to match the file rather than guess. Task 6 step 2
says the same about `ProviderPolicy`'s constructor.
