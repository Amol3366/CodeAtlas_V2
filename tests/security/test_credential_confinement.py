"""Where the credential must never appear.

The controls in this file are the reason the feature is allowed to exist. They
are written as their own suite rather than folded into the contract tests
because they assert *absence*, and absence is what silently stops being true.

Every test blanks `OPENAI_API_KEY` rather than deleting it: `create_app` calls
`load_env_file`, which fills any key the environment lacks, so a deleted
variable is refilled from the developer's real `.env` before the first request.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.application.credentials import CredentialService
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.settings.credentials import (
    OPENAI_CREDENTIAL_NAME,
    resolve_openai_api_key,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SECRET = "sk-" + "confine" * 6


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


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "db.sqlite"
    with connect(path) as connection:
        apply_migrations(connection)
    return path


def test_a_stored_key_never_enters_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git is invoked as a subprocess and inherits this environment.

    A key placed in ``os.environ`` is handed to every Git call for the life of
    the server, which is why resolution returns a value rather than publishing
    one.

    ``resolve_openai_api_key`` is called explicitly rather than relying on
    ``status()``. A stored key makes ``status()`` take its own branch and never
    reach the resolver, so a version of this test that only saved and read the
    status passed even against a deliberately leaking resolver — verified by
    mutation. The leak path has to be executed for its absence to mean
    anything.
    """
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "")
    store = FakeStore()
    service = CredentialService(store)

    service.set_openai_key(SECRET)
    assert service.status().configured is True

    assert resolve_openai_api_key(store) == SECRET

    assert os.environ.get(OPENAI_CREDENTIAL_NAME, "") == ""
    assert SECRET not in "".join(os.environ.values())


def test_a_stored_key_is_absent_from_the_database(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database is copied by backup and attached to bug reports."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "")
    CredentialService(FakeStore()).set_openai_key(SECRET)

    assert SECRET.encode() not in database.read_bytes()


def test_a_rejected_write_does_not_log_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "")
    service = CredentialService(FakeStore())

    with caplog.at_level(logging.DEBUG):
        service.set_openai_key(SECRET)
        with pytest.raises(InvalidRequestError):
            service.set_openai_key("s" * 501)

    assert SECRET not in caplog.text


def test_a_validation_error_never_quotes_the_key() -> None:
    """The message reaches the client, so it must describe the rule rather
    than the value that broke it."""
    service = CredentialService(FakeStore())

    with pytest.raises(InvalidRequestError) as raised:
        service.set_openai_key(SECRET + "s" * 500)

    assert SECRET not in str(raised.value)
    assert SECRET not in str(raised.value.details)


def test_diagnostics_and_status_never_carry_the_key(
    database: Path, monkeypatch: pytest.MonkeyPatch, sample_repo: Path
) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "")
    with TestClient(create_app(database, watch=False)) as client:
        written = client.put("/v1/credentials/openai", json={"api_key": SECRET})
        if written.status_code != 200:
            pytest.skip("no credential store on this platform")
        try:
            repository_id = client.post(
                "/v1/repositories", json={"path": str(sample_repo)}
            ).json()["repository_id"]

            bodies = [
                client.get(f"/v1/repositories/{repository_id}/diagnostics").text,
                client.get(f"/v1/repositories/{repository_id}/status").text,
                client.get("/v1/credentials").text,
                client.get("/v1/models").text,
                client.get(
                    "/v1/settings", params={"repository_id": repository_id}
                ).text,
            ]
            assert all(SECRET not in body for body in bodies)
        finally:
            client.delete("/v1/credentials/openai")
