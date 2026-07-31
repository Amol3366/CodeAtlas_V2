"""`GET /v1/repositories/{id}/semantic-status`.

Section 12.1 named this endpoint and Phase 7 is where it gets built. It answers
the product's fourth and fifth questions — how current is the evidence, and what
does CodeAtlas not know — for the one index that is allowed to lag behind the
snapshot it describes.

The distinction the response has to preserve, and the reason it is not simply a
number: **"no provider" is not "zero coverage".** A repository that opted into
nothing is not partially indexed; the question does not apply to it. Reporting
0.0 there would raise a partial-freshness banner over a product working exactly
as designed, on every installation that never enabled anything.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path, watch=False)) as test_client:
        yield test_client


@pytest.fixture()
def repository_id(client: TestClient, sample_repo: Path) -> str:
    response = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert response.status_code == 201, response.text
    identifier = str(response.json()["repository_id"])
    assert client.post(f"/v1/repositories/{identifier}/index").status_code == 200
    return identifier


def test_a_repository_that_opted_into_nothing_reports_disabled(
    client: TestClient, repository_id: str
) -> None:
    """The default on every installation."""
    response = client.get(f"/v1/repositories/{repository_id}/semantic-status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["provider"] == "none"


def test_a_disabled_repository_reports_no_coverage_rather_than_zero(
    client: TestClient, repository_id: str
) -> None:
    """Zero would read as "indexed, nothing found" and show a partial-freshness
    banner over a product working exactly as designed."""
    body = client.get(f"/v1/repositories/{repository_id}/semantic-status").json()

    assert body["coverage"] is None
    assert body["embedded_count"] is None
    assert body["pending_count"] is None


def test_the_response_names_the_snapshot_it_describes(
    client: TestClient, repository_id: str
) -> None:
    """Coverage is a claim about one snapshot. Without the ID it is a number
    with no referent, and a client could show it beside a newer snapshot."""
    body = client.get(f"/v1/repositories/{repository_id}/semantic-status").json()

    active = client.get(
        f"/v1/repositories/{repository_id}/snapshots/active"
    ).json()
    assert body["snapshot_id"] == active["snapshot_id"]


def test_an_unindexed_repository_is_reported_not_refused(
    client: TestClient, sample_repo: Path
) -> None:
    """Asking about semantic coverage before the first index is an ordinary
    question with an ordinary answer."""
    created = client.post(
        "/v1/repositories", json={"path": str(sample_repo / "src")}
    )
    identifier = created.json()["repository_id"]

    response = client.get(f"/v1/repositories/{identifier}/semantic-status")

    assert response.status_code == 200, response.text
    assert response.json()["snapshot_id"] is None


def test_an_unknown_repository_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/v1/repositories/repo_missing/semantic-status")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_the_two_surfaces_agree_for_a_repository_with_no_provider(
    client: TestClient, repository_id: str
) -> None:
    """The envelope's `semantic_coverage` is a non-nullable float, so it says
    0.0 where `/semantic-status` says null. For a disabled repository those
    agree: nothing is covered because nothing was asked for.

    They would *not* agree for an enabled repository — the envelope's value is
    still a placeholder outside a fused answer. That is P7-08's to close, once
    a provider can be enabled through the API at all; it cannot be driven by a
    failing test before then.
    """
    coverage = client.get(
        f"/v1/repositories/{repository_id}/semantic-status"
    ).json()["coverage"]
    reported = client.get(f"/v1/repositories/{repository_id}/status").json()

    assert coverage is None
    assert reported["snapshot"]["semantic_coverage"] == 0.0


def test_no_absolute_path_is_returned(
    client: TestClient, repository_id: str, sample_repo: Path
) -> None:
    """Section 4.4: a diagnostic surface is a leak surface."""
    body = client.get(f"/v1/repositories/{repository_id}/semantic-status").text

    assert str(sample_repo) not in body
