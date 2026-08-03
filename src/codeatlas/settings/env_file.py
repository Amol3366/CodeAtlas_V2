"""Reading `.env` from a fixed location beside CodeAtlas itself.

Three rules make this safe enough to load automatically at startup.

**The location is fixed, not discovered.** The file is read from
`$CODEATLAS_ENV_FILE`, or from the CodeAtlas root resolved through the
package's own path — never from the current working directory. A
current-directory search would let a repository you merely *index* configure
the tool that indexes it, which inverts `CLAUDE.md` Section 4.4: repository
content is data, never instructions.

**The real environment always wins.** Values are applied only where the
environment has nothing, so an exported variable outranks the file. A stale
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

# Which repositories an ephemeral session registers and indexes at startup.
# Semicolon-separated absolute paths. This names *what to open*, never whether a
# repository may transmit — that stays in SQLite, per repository.
EPHEMERAL_REPOSITORIES_VARIABLE = "CODEATLAS_EPHEMERAL_REPOSITORIES"

# Answer generation. These name *which* model writes the prose; whether a
# repository generates at all is stored per repository in SQLite, and no
# variable here can change that.
OLLAMA_ANSWER_MODEL_VARIABLE = "CODEATLAS_OLLAMA_ANSWER_MODEL"
OLLAMA_BASE_URL_VARIABLE = "CODEATLAS_OLLAMA_BASE_URL"
OPENAI_ANSWER_MODEL_VARIABLE = "CODEATLAS_OPENAI_ANSWER_MODEL"
ANSWER_TIMEOUT_VARIABLE = "CODEATLAS_ANSWER_TIMEOUT_SECONDS"

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
    # `utf-8-sig` already removes a byte-order mark when the file is read, but
    # this function is also called directly on text from elsewhere. Written as
    # an escape rather than a literal, which would be invisible in the source.
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
    except (OSError, UnicodeDecodeError):
        # Missing is the normal case and needs no warning. Unreadable and
        # undecodable are rarer and equally non-fatal: deterministic operation
        # needs no settings at all.
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


def configured_ephemeral_repositories() -> tuple[str, ...]:
    """Paths an ephemeral session should register at startup, in order.

    Semicolons separate entries because a Windows path contains a colon and may
    contain spaces, which rules out both of the other obvious separators.
    Blanks are dropped and duplicates removed: a trailing separator is the most
    common hand-edit, and registering the same root twice fails the second time
    with an error that reads like a defect rather than a typo.
    """
    raw = _text(EPHEMERAL_REPOSITORIES_VARIABLE)
    if raw is None:
        return ()

    ordered: list[str] = []
    for entry in raw.split(";"):
        candidate = entry.strip()
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


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


def configured_ollama_answer_model() -> str | None:
    """The configured local answer model, or ``None`` for the default."""
    return _text(OLLAMA_ANSWER_MODEL_VARIABLE)


def configured_ollama_base_url() -> str | None:
    """Where Ollama listens, or ``None`` for loopback on its default port."""
    return _text(OLLAMA_BASE_URL_VARIABLE)


def configured_openai_answer_model() -> str | None:
    """The configured hosted answer model, or ``None`` for the default."""
    return _text(OPENAI_ANSWER_MODEL_VARIABLE)


def configured_answer_timeout_seconds() -> int | None:
    """The generation timeout in seconds, or ``None`` for the built-in bound.

    Refuses anything that is not a positive integer rather than falling back.
    A zero or negative timeout would fail every generation instantly, which is
    indistinguishable from the feature being broken — and a typo here is much
    likelier than a deliberate zero.
    """
    raw = _text(ANSWER_TIMEOUT_VARIABLE)
    if raw is None:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        seconds = 0
    if seconds <= 0:
        raise InvalidRequestError(
            f"{ANSWER_TIMEOUT_VARIABLE} must be a positive whole number.",
            details={"variable": ANSWER_TIMEOUT_VARIABLE},
        )
    return seconds


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
    "ANSWER_TIMEOUT_VARIABLE",
    "ENV_FILE_NAME",
    "ENV_FILE_VARIABLE",
    "LOCAL_MODEL_VARIABLE",
    "OLLAMA_ANSWER_MODEL_VARIABLE",
    "OLLAMA_BASE_URL_VARIABLE",
    "OPENAI_ANSWER_MODEL_VARIABLE",
    "OPENAI_DIMENSIONS_VARIABLE",
    "OPENAI_MODEL_VARIABLE",
    "LoadedEnv",
    "codeatlas_root",
    "configured_answer_timeout_seconds",
    "configured_local_model",
    "configured_ollama_answer_model",
    "configured_ollama_base_url",
    "configured_openai_answer_model",
    "configured_openai_dimensions",
    "configured_openai_model",
    "env_file_path",
    "load_env_file",
    "parse_env_text",
]
