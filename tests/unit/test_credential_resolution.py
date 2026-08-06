"""The precedence ladder, and the rule that the key stays out of the environment.

Mirrors ADR-0014's policy -> .env -> default ordering, so the codebase has one
precedence rule rather than two that disagree.
"""

from __future__ import annotations

import os

import pytest

from codeatlas.settings.credentials import (
    OPENAI_CREDENTIAL_NAME,
    UnavailableCredentialStore,
    resolve_openai_api_key,
)


class FakeStore:
    """A store holding exactly what a test puts in it."""

    def __init__(self, value: str | None) -> None:
        self._value = value

    def is_available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        return self._value

    def set(self, name: str, value: str) -> None:
        self._value = value

    def clear(self, name: str) -> None:
        self._value = None


def test_the_stored_key_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(FakeStore("sk-from-store")) == "sk-from-store"


def test_env_is_used_when_the_store_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(FakeStore(None)) == "sk-from-env"


def test_env_is_used_when_the_store_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(UnavailableCredentialStore()) == "sk-from-env"


def test_nothing_anywhere_resolves_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    assert resolve_openai_api_key(FakeStore(None)) is None


def test_a_blank_stored_value_falls_through_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty entry is indistinguishable from no entry to a user, so it must
    not shadow a working .env value."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(FakeStore("   ")) == "sk-from-env"


def test_resolution_never_publishes_the_key_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subprocess-inheritance constraint, as a test rather than a comment.

    CodeAtlas shells out to Git, and a child process inherits its parent's
    environment. A key placed in ``os.environ`` is handed to every Git
    invocation for the life of the server.
    """
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)

    assert resolve_openai_api_key(FakeStore("sk-must-not-leak")) == "sk-must-not-leak"

    assert OPENAI_CREDENTIAL_NAME not in os.environ
    assert "sk-must-not-leak" not in "".join(os.environ.values())
