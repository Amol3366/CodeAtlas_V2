"""What `.env` must never do.

The credential is the asset. These assert the boundaries rather than the
feature: that configuration cannot become consent, that a repository cannot
become configuration, and that the key never leaves the process it was read
into.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.repositories.ignore_rules import IgnoreRules
from codeatlas.repositories.scanner import RepositoryScanner
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

SECRET = "sk-test-not-a-real-key-abcdef0123456789"


def _write_env(directory: Path, body: str) -> Path:
    target = directory / ".env"
    target.write_text(body, encoding="utf-8")
    return target


def _repository(database: Path, root: Path) -> str:
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root), display_name="fixture")
        )
    return repository.repository_id


def test_configuration_cannot_become_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every variable set, policy untouched: still no provider."""
    monkeypatch.setenv(OPENAI_API_KEY_VARIABLE, SECRET)
    monkeypatch.setenv(LOCAL_MODEL_VARIABLE, "BAAI/bge-small-en-v1.5")

    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    database = tmp_path / "codeatlas.db"
    repository_id = _repository(database, root)

    with connect(database) as connection:
        policy = build_services(connection).settings.get(repository_id)

    assert policy.embedding_provider is EmbeddingProviderKind.NONE

    provider = build_embedding_provider(
        ProviderPolicy(
            repository_id=repository_id,
            embedding_provider=EmbeddingProviderKind.NONE,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=policy.updated_at,
        )
    )
    assert isinstance(provider, NoEmbeddingProvider)


def test_a_repository_cannot_supply_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile `.env` in the directory you run from is not read."""
    monkeypatch.delenv(ENV_FILE_VARIABLE, raising=False)
    monkeypatch.delenv("HOSTILE_SETTING", raising=False)
    _write_env(tmp_path, "HOSTILE_SETTING=owned\n")
    monkeypatch.chdir(tmp_path)

    load_env_file()

    assert "HOSTILE_SETTING" not in os.environ


def test_the_credential_is_absent_from_every_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENAI_API_KEY_VARIABLE, SECRET)

    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    database = tmp_path / "codeatlas.db"
    repository_id = _repository(database, root)

    app = create_app(database, watch=False)
    with TestClient(app) as client:
        bodies = [
            client.get(f"/v1/settings?repository_id={repository_id}").text,
            client.get("/v1/models").text,
            client.get(f"/v1/repositories/{repository_id}/diagnostics").text,
            client.get("/v1/settings").text,  # missing parameter: error envelope
        ]

    for body in bodies:
        assert SECRET not in body
        # The tail alone would be enough to confirm a guess.
        assert SECRET[-12:] not in body


def test_the_loader_returns_names_and_never_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXAMPLE_SECRET", raising=False)
    path = _write_env(tmp_path, f"EXAMPLE_SECRET={SECRET}\n")

    result = load_env_file(path)

    assert result.applied == ("EXAMPLE_SECRET",)
    assert SECRET not in repr(result)


def test_a_hostile_file_cannot_deny_service(tmp_path: Path) -> None:
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


def test_binary_content_is_not_fatal(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_bytes(bytes(range(256)) * 16)

    assert load_env_file(target).applied == ()


def test_env_files_are_not_scanned(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = RepositoryScanner().scan(tmp_path, IgnoreRules.load(tmp_path))

    scanned = {record.relative_path for record in result.files}
    assert "main.py" in scanned
    assert ".env" not in scanned
