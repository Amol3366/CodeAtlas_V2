"""The /v1 REST adapter must expose the application services unchanged."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.contracts import QueryResponse
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path)) as test_client:
        yield test_client


def _register(client: TestClient, root: Path) -> str:
    response = client.post("/v1/repositories", json={"path": str(root)})
    assert response.status_code == 201, response.text
    repository_id: str = response.json()["repository_id"]
    return repository_id


def test_register_index_and_query_round_trip(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register(client, sample_repo)

    indexed = client.post(f"/v1/repositories/{repository_id}/index")
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["state"] == "active"

    queried = client.post(
        "/v1/query",
        json={
            "repository_id": repository_id,
            "query": "PaymentService.capture",
            "mode": "exact_symbol",
        },
    )
    assert queried.status_code == 200, queried.text
    response = QueryResponse.model_validate(queried.json())
    assert response.evidence[0].file_path == "src/payments/service.py"
    assert (response.evidence[0].start_line, response.evidence[0].end_line) == (7, 8)


def test_repository_listing_and_fetch(client: TestClient, sample_repo: Path) -> None:
    repository_id = _register(client, sample_repo)

    listed = client.get("/v1/repositories")
    assert listed.status_code == 200
    assert [item["repository_id"] for item in listed.json()] == [repository_id]

    fetched = client.get(f"/v1/repositories/{repository_id}")
    assert fetched.status_code == 200
    assert fetched.json()["display_name"] == "sample_repo"


def test_status_and_diagnostics(client: TestClient, sample_repo: Path) -> None:
    repository_id = _register(client, sample_repo)
    client.post(f"/v1/repositories/{repository_id}/index")

    status = client.get(f"/v1/repositories/{repository_id}/status")
    assert status.status_code == 200
    body = status.json()
    assert body["file_count"] == 3
    assert body["symbol_count"] > 0
    assert body["snapshot"]["freshness"] == "fresh"

    diagnostics = client.get(f"/v1/repositories/{repository_id}/diagnostics")
    assert diagnostics.status_code == 200
    assert "limits" in diagnostics.json()


def test_active_snapshot_endpoint(client: TestClient, sample_repo: Path) -> None:
    repository_id = _register(client, sample_repo)
    before = client.get(f"/v1/repositories/{repository_id}/snapshots/active")
    assert before.status_code == 409
    assert before.json()["error"]["code"] == "SNAPSHOT_NOT_READY"

    client.post(f"/v1/repositories/{repository_id}/index")
    after = client.get(f"/v1/repositories/{repository_id}/snapshots/active")
    assert after.status_code == 200
    assert after.json()["snapshot_id"].startswith("snap_")


def test_unknown_repository_returns_404_with_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.get("/v1/repositories/repo_missing")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "REPOSITORY_NOT_FOUND"
    assert error["request_id"]
    assert error["retryable"] is False


def test_query_before_indexing_returns_409(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register(client, sample_repo)
    response = client.post(
        "/v1/query",
        json={
            "repository_id": repository_id,
            "query": "PaymentService",
            "mode": "exact_symbol",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SNAPSHOT_NOT_READY"
    assert response.json()["error"]["retryable"] is True


def test_unsupported_query_mode_returns_400(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register(client, sample_repo)
    response = client.post(
        "/v1/query",
        json={
            "repository_id": repository_id,
            "query": "PaymentService",
            "mode": "semantic",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_QUERY_MODE"


def test_duplicate_registration_returns_409(
    client: TestClient, sample_repo: Path
) -> None:
    _register(client, sample_repo)
    response = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPOSITORY_ALREADY_REGISTERED"


def test_missing_directory_registration_returns_400(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(
        "/v1/repositories", json={"path": str(tmp_path / "does-not-exist")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"].startswith("PATH_")


@pytest.mark.skipif(os.name != "nt", reason="Windows system path")
def test_registering_a_file_instead_of_a_directory_returns_400(
    client: TestClient, tmp_path: Path
) -> None:
    target = tmp_path / "not-a-directory.txt"
    target.write_text("x", encoding="utf-8")
    response = client.post("/v1/repositories", json={"path": str(target)})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PATH_NOT_ALLOWED"


def test_malformed_request_body_returns_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.post("/v1/repositories", json={"wrong_field": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_overlong_query_returns_400(client: TestClient, sample_repo: Path) -> None:
    repository_id = _register(client, sample_repo)
    client.post(f"/v1/repositories/{repository_id}/index")
    response = client.post(
        "/v1/query",
        json={
            "repository_id": repository_id,
            "query": "x" * 600,
            "mode": "exact_symbol",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_request_id_header_is_echoed(client: TestClient) -> None:
    response = client.get(
        "/v1/repositories/repo_missing", headers={"X-Request-Id": "trace-123"}
    )
    assert response.json()["error"]["request_id"] == "trace-123"


def test_unknown_symbol_returns_an_abstention_not_an_error(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register(client, sample_repo)
    client.post(f"/v1/repositories/{repository_id}/index")
    response = client.post(
        "/v1/query",
        json={
            "repository_id": repository_id,
            "query": "NoSuchSymbol",
            "mode": "exact_symbol",
        },
    )
    assert response.status_code == 200
    body = QueryResponse.model_validate(response.json())
    assert body.evidence == []
    assert body.answer.claims == []


def _indexed(client: TestClient, root: Path) -> str:
    """Register and index a repository through the API, returning its ID."""
    repository_id = _register(client, root)
    indexed = client.post(f"/v1/repositories/{repository_id}/index")
    assert indexed.status_code == 200, indexed.text
    return repository_id


def test_search_text_returns_a_contract_response(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _indexed(client, sample_repo)

    response = client.get(
        "/v1/search/text", params={"repository_id": repository_id, "q": "claim"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "1.1"
    assert body["evidence"]
    assert all(
        item["snapshot_id"] == body["snapshot"]["snapshot_id"]
        for item in body["evidence"]
    )


def test_search_files_and_symbols_are_available(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _indexed(client, sample_repo)

    files = client.get(
        "/v1/search/files", params={"repository_id": repository_id, "q": "payments"}
    )
    symbols = client.get(
        "/v1/search/symbols", params={"repository_id": repository_id, "q": "capture"}
    )

    assert files.status_code == 200
    assert symbols.status_code == 200
    assert symbols.json()["evidence"][0]["symbol"] == "PaymentService.capture"
    assert symbols.json()["evidence"][0]["derivation"] == "deterministic"


@pytest.mark.parametrize("hostile", ["***", "^^^^", "", "   ", "-- ;"])
def test_a_hostile_search_query_returns_the_error_envelope(
    client: TestClient, sample_repo: Path, hostile: str
) -> None:
    repository_id = _indexed(client, sample_repo)

    response = client.get(
        "/v1/search/text", params={"repository_id": repository_id, "q": hostile}
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "SEARCH_QUERY_INVALID"
    assert error["request_id"]
    assert "Traceback" not in response.text


def test_a_hostile_query_that_parses_returns_bounded_results(
    client: TestClient, sample_repo: Path
) -> None:
    """FTS operators supplied by a user become literal terms, not syntax.

    `" OR "" : *` reduces to the single term "or", so the correct outcome is an
    ordinary bounded response — not an error, and emphatically not every row.
    """
    repository_id = _indexed(client, sample_repo)

    response = client.get(
        "/v1/search/text",
        params={"repository_id": repository_id, "q": '" OR "" : *'},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["evidence"]) <= 25


def test_search_on_an_unknown_repository_is_404(
    client: TestClient, sample_repo: Path
) -> None:
    _indexed(client, sample_repo)
    response = client.get(
        "/v1/search/text", params={"repository_id": "repo_missing", "q": "claim"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_rollback_without_a_target_is_409(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _indexed(client, sample_repo)

    response = client.post(f"/v1/repositories/{repository_id}/rollback")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_ROLLBACK_TARGET"


def test_rollback_restores_the_previous_snapshot(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _indexed(client, sample_repo)
    first = client.get(f"/v1/repositories/{repository_id}/snapshots/active").json()

    path = sample_repo / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n    def extra(self) -> int:\n"
        "        return 1\n",
        encoding="utf-8",
    )
    client.post(f"/v1/repositories/{repository_id}/index")

    response = client.post(f"/v1/repositories/{repository_id}/rollback")

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == first["snapshot_id"]
