"""Serving the built web application from the API process.

In development the browser talks to Vite, which proxies `/v1` to the API. A
packaged build has no Vite, so the API serves the built assets itself — and the
browser still sees **one origin**, which is what lets the API keep its
no-CORS, loopback-only posture (ADR-0006 decision 9).

Two rules make that safe, and both are easy to get wrong:

* A client-side route like `/conversations/{id}` is not a file. A deep link or a
  reload must return `index.html` so the router can take over.
* That fallback must **not** swallow `/v1`. An unknown API path has to stay a
  JSON 404; returning HTML to a client expecting JSON turns a clear failure into
  a parse error somewhere else.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.api.web import web_assets_path
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def assets(tmp_path: Path) -> Path:
    """A stand-in for `apps/web/dist`, with the shape Vite produces."""
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        "<!doctype html><title>CodeAtlas</title><div id=root></div>",
        encoding="utf-8",
    )
    (root / "assets" / "index.js").write_text("export const x = 1;\n", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return root


@pytest.fixture()
def client(tmp_path: Path, assets: Path) -> Iterator[TestClient]:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
    app = create_app(database, watch=False, web_assets=assets)
    with TestClient(app) as test_client:
        yield test_client


def test_the_root_serves_the_application_shell(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "CodeAtlas" in response.text


def test_the_application_shell_is_not_cached(client: TestClient) -> None:
    """A stale shell points the browser at stale built asset hashes."""
    for path in ("/", "/index.html", "/settings"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["cache-control"] == (
            "no-store, max-age=0, must-revalidate"
        )
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["expires"] == "0"


def test_a_built_asset_is_served(client: TestClient) -> None:
    response = client.get("/assets/index.js")

    assert response.status_code == 200
    assert "export const x" in response.text


def test_a_client_side_route_falls_back_to_the_shell(client: TestClient) -> None:
    """A deep link or a reload on /conversations/{id} must not 404."""
    response = client.get("/conversations/conv_abc123")

    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_an_unknown_api_path_stays_a_json_404(client: TestClient) -> None:
    """The rule the fallback must not break.

    P6-08 found this returning a *bare* 404 — right status, no content type,
    empty body. Not HTML, so the fallback rule held, but a client that always
    reads `error.code` met a parse failure rather than a stable code.
    """
    response = client.get("/v1/not-a-real-endpoint")

    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["error"]["request_id"]


def test_a_wrong_method_on_a_real_endpoint_is_the_envelope(
    client: TestClient,
) -> None:
    response = client.delete("/v1/repositories")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_the_shell_is_still_served_without_an_envelope(client: TestClient) -> None:
    """Only `/v1` is translated. A missing asset stays a plain 404, because the
    static mount and the client-side fallback depend on that behavior."""
    response = client.get("/assets/not-a-real-file.js")

    assert response.status_code == 404
    assert "error" not in response.text


def test_an_api_error_is_still_the_error_envelope(client: TestClient) -> None:
    response = client.get("/v1/repositories/repo_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_the_api_still_answers_with_the_web_app_mounted(client: TestClient) -> None:
    """Packaging changes no runtime contract: `/v1` behaves exactly as before."""
    response = client.get("/v1/repositories")

    assert response.status_code == 200
    assert response.json() == []


def test_a_missing_asset_below_assets_is_a_404_not_the_shell(
    client: TestClient,
) -> None:
    """Returning HTML for a missing script produces a confusing console error
    rather than an honest one."""
    response = client.get("/assets/does-not-exist.js")

    assert response.status_code == 404


def test_the_application_runs_without_web_assets(tmp_path: Path) -> None:
    """The API alone is a supported way to run: CLI and MCP users need no SPA."""
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)

    with TestClient(create_app(database, watch=False)) as client:
        assert client.get("/v1/repositories").status_code == 200
        assert client.get("/").status_code == 404


def test_an_assets_directory_that_does_not_exist_is_ignored(tmp_path: Path) -> None:
    """A packaging mistake must not stop the API from serving.

    Refusing to boot because the SPA is missing would turn a cosmetic packaging
    error into a total outage for the CLI and MCP surfaces too.
    """
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)

    app = create_app(database, watch=False, web_assets=tmp_path / "absent")
    with TestClient(app) as client:
        assert client.get("/v1/repositories").status_code == 200


def test_the_fallback_does_not_serve_files_outside_the_assets_directory(
    client: TestClient, tmp_path: Path
) -> None:
    """Traversal, on the one route that takes an arbitrary path."""
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve me", encoding="utf-8")

    for attempt in (
        "/../secret.txt",
        "/assets/../../secret.txt",
        "/%2e%2e/secret.txt",
    ):
        response = client.get(attempt)
        assert "do not serve me" not in response.text


# --- Locating the assets ---------------------------------------------------


def test_web_assets_are_found_in_a_source_checkout() -> None:
    """`apps/web/dist` after a build. Absent before one, which is not an error."""
    found = web_assets_path()

    assert found is None or found.name == "dist"


def test_a_frozen_build_looks_beside_the_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PyInstaller unpacks data next to the binary, not next to the source.

    `sys._MEIPASS` is the only reliable way to find bundled data in a frozen
    build; a path derived from `__file__` points into the archive.
    """
    bundled = tmp_path / "_internal" / "web"
    bundled.mkdir(parents=True)
    (bundled / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "_internal"), raising=False)

    assert web_assets_path() == bundled
