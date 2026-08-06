"""The application boundary adapters call for credential state."""

from __future__ import annotations

import pytest

from codeatlas.application.credentials import CredentialService
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.settings.credentials import OPENAI_CREDENTIAL_NAME


class FakeStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def is_available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def clear(self, name: str) -> None:
        self.values.pop(name, None)


def test_nothing_configured_is_reported_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    status = CredentialService(FakeStore()).status()

    assert status.configured is False
    assert status.source is None
    assert status.store_available is True


def test_a_saved_key_reports_the_store_as_its_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    service = CredentialService(FakeStore())

    status = service.set_openai_key("sk-saved")

    assert status.configured is True
    assert status.source == "credential_store"


def test_an_env_key_is_reported_as_coming_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user who saved nothing but sees "configured" needs to know why."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    status = CredentialService(FakeStore()).status()

    assert status.configured is True
    assert status.source == "env"


def test_a_saved_key_shadows_env_in_the_reported_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reported source must match what would actually be used."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    service = CredentialService(FakeStore())

    status = service.set_openai_key("sk-saved")

    assert status.source == "credential_store"


def test_clearing_removes_the_stored_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    service = CredentialService(FakeStore())
    service.set_openai_key("sk-saved")

    status = service.clear_openai_key()

    assert status.configured is False
    assert status.source is None


def test_clearing_does_not_touch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing must not edit a file the user owns, so a .env key survives."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    service = CredentialService(FakeStore())
    service.set_openai_key("sk-saved")

    status = service.clear_openai_key()

    assert status.configured is True
    assert status.source == "env"


def test_an_empty_key_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        CredentialService(FakeStore()).set_openai_key("   ")


def test_an_overlong_key_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        CredentialService(FakeStore()).set_openai_key("s" * 501)


def test_a_key_is_stored_trimmed() -> None:
    """A pasted key often carries whitespace, and a trailing newline in an
    Authorization header is a failure with no useful message."""
    store = FakeStore()
    CredentialService(store).set_openai_key("  sk-padded  ")

    assert store.values[OPENAI_CREDENTIAL_NAME] == "sk-padded"
