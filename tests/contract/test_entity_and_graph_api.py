"""REST contracts for addressable entities and graph relations.

The evidence round-trip is the test that matters most here: an ID handed out by
one query must fetch back the same region, and must report drift rather than
stale content once the file changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SERVICE_PY = (
    "from .idempotency import IdempotencyStore\n"
    "\n"
    "class PaymentService:\n"
    "    def __init__(self, store: IdempotencyStore) -> None:\n"
    "        self.store = store\n"
    "\n"
    "    def capture(self, key: str) -> str:\n"
    "        return self.store.claim(key)\n"
)
IDEMPOTENCY_PY = (
    "class IdempotencyStore:\n"
    "    def claim(self, key: str) -> str:\n"
    "        return key\n"
)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "src" / "payments").mkdir(parents=True)
    (root / "src" / "payments" / "service.py").write_text(SERVICE_PY, encoding="utf-8")
    (root / "src" / "payments" / "idempotency.py").write_text(
        IDEMPOTENCY_PY, encoding="utf-8"
    )
    return root


@pytest.fixture()
def client(tmp_path: Path, repo_root: Path) -> Iterator[tuple[TestClient, str]]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path)) as test_client:
        created = test_client.post("/v1/repositories", json={"path": str(repo_root)})
        assert created.status_code == 201, created.text
        repository_id = created.json()["repository_id"]
        indexed = test_client.post(f"/v1/repositories/{repository_id}/index")
        assert indexed.status_code == 200, indexed.text
        yield test_client, repository_id


def _first_evidence_id(client: TestClient, repository_id: str) -> str:
    response = client.get(
        "/v1/symbols/PaymentService.capture/relations",
        params={"repository_id": repository_id, "view": "callees"},
    )
    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert evidence, "expected the callees query to cite evidence"
    return str(evidence[0]["evidence_id"])


# --- Graph relations ----------------------------------------------------------


def test_symbol_relations_returns_a_contract_response(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/symbols/PaymentService.capture/relations",
        params={"repository_id": repository_id, "view": "callees"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "1.0"
    assert "relation_paths" in payload
    assert payload["snapshot"]["snapshot_id"]


def test_an_unknown_view_is_rejected_at_the_boundary(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/symbols/PaymentService.capture/relations",
        params={"repository_id": repository_id, "view": "nonsense"},
    )

    assert response.status_code == 422


def test_a_depth_above_the_maximum_is_refused(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/symbols/PaymentService.capture/relations",
        params={"repository_id": repository_id, "view": "callees", "depth": 50},
    )

    assert response.status_code == 422


# --- Evidence addressing ------------------------------------------------------


def test_a_cited_evidence_id_fetches_back_the_same_region(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client
    evidence_id = _first_evidence_id(test_client, repository_id)

    fetched = test_client.get(
        f"/v1/evidence/{evidence_id}", params={"repository_id": repository_id}
    )

    assert fetched.status_code == 200, fetched.text
    item = fetched.json()["evidence"][0]
    assert item["evidence_id"] == evidence_id
    assert item["file_path"] == "src/payments/service.py"


def test_fetching_evidence_reports_drift_rather_than_stale_content(
    client: tuple[TestClient, str], repo_root: Path
) -> None:
    test_client, repository_id = client
    evidence_id = _first_evidence_id(test_client, repository_id)

    target = repo_root / "src" / "payments" / "service.py"
    target.write_text(SERVICE_PY + "\nEXTRA = 1\n", encoding="utf-8")

    fetched = test_client.get(
        f"/v1/evidence/{evidence_id}", params={"repository_id": repository_id}
    )

    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["evidence"] == []
    assert "EVIDENCE_STALE_FILE_CONTENT" in payload["warnings"]
    assert payload["snapshot"]["freshness"] == "stale"


def test_an_unknown_evidence_id_is_a_404_with_a_stable_code(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/evidence/ev_does_not_exist", params={"repository_id": repository_id}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"


# --- Files and symbols --------------------------------------------------------


def test_a_file_can_be_fetched_by_id(client: tuple[TestClient, str]) -> None:
    test_client, repository_id = client
    listing = test_client.get(f"/v1/repositories/{repository_id}/files")
    assert listing.status_code == 200
    file_id = listing.json()["files"][0]["file_id"]

    response = test_client.get(
        f"/v1/files/{file_id}", params={"repository_id": repository_id}
    )

    assert response.status_code == 200
    assert response.json()["file"]["file_id"] == file_id


def test_an_unknown_file_id_is_a_404_with_a_stable_code(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/files/file_missing", params={"repository_id": repository_id}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_an_unknown_symbol_id_is_a_404_with_a_stable_code(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/symbols/sym_missing", params={"repository_id": repository_id}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_every_error_uses_the_contract_envelope(
    client: tuple[TestClient, str],
) -> None:
    test_client, repository_id = client

    response = test_client.get(
        "/v1/evidence/ev_missing", params={"repository_id": repository_id}
    )

    error = response.json()["error"]
    assert set(error) >= {"code", "message", "request_id", "retryable", "details"}
    # No stack trace, no local path.
    assert "Traceback" not in error["message"]
    assert "C:\\" not in error["message"]
