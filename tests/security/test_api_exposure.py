"""The local API stays on loopback and leaks nothing in its errors."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    return create_app(database_path)


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_default_bind_host_is_loopback() -> None:
    from apps.api.main import HOST

    assert HOST == "127.0.0.1"


def test_no_cors_middleware_is_registered(app: FastAPI) -> None:
    names = [str(middleware.cls) for middleware in app.user_middleware]
    assert not any("CORSMiddleware" in name for name in names)


def test_error_responses_contain_no_absolute_paths_or_tracebacks(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(
        "/v1/repositories", json={"path": str(tmp_path / "missing")}
    )
    assert response.status_code == 400
    body = response.text
    assert "Traceback" not in body
    assert str(tmp_path) not in body
    assert "missing" not in body


def test_internal_failures_do_not_leak_details(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/v1/_boom")
    def boom() -> None:
        raise RuntimeError("secret detail C:/Users/private/token")

    with TestClient(app, raise_server_exceptions=False) as unsafe_client:
        response = unsafe_client.get("/v1/_boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in response.text
    assert "C:/Users/private" not in response.text


def test_repository_responses_do_not_expose_the_absolute_root(
    client: TestClient, sample_repo: Path
) -> None:
    created = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert created.status_code == 201
    assert str(sample_repo.parent) not in created.text
