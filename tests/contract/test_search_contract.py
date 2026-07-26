"""Search responses satisfy the same public contract as exact lookup."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import CONTRACT_VERSION, Derivation, QueryResponse
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_LEXICAL_DERIVATIONS = {
    Derivation.HIGH_CONFIDENCE_HEURISTIC,
    Derivation.DETERMINISTIC,
    Derivation.STATIC_RESOLVED,
}


@dataclass
class Harness:
    services: ApplicationServices
    repository_id: str
    root: Path


@pytest.fixture()
def harness(tmp_path: Path, sample_repo: Path) -> Iterator[Harness]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        yield Harness(
            services=services,
            repository_id=repository.repository_id,
            root=sample_repo,
        )


def _responses(harness: Harness) -> list[QueryResponse]:
    return [
        harness.services.search.search_text(
            SearchRequest(harness.repository_id, "claim", "req-1")
        ),
        harness.services.search.search_files(
            SearchRequest(harness.repository_id, "payments", "req-2")
        ),
        harness.services.search.search_symbols(
            SearchRequest(harness.repository_id, "capture", "req-3")
        ),
    ]


def test_every_search_response_round_trips_through_the_contract(
    harness: Harness,
) -> None:
    for response in _responses(harness):
        restored = QueryResponse.model_validate_json(response.model_dump_json())
        assert restored == response
        assert restored.contract_version == CONTRACT_VERSION


def test_every_claim_resolves_to_returned_evidence(harness: Harness) -> None:
    for response in _responses(harness):
        available = {item.evidence_id for item in response.evidence}
        for claim in response.answer.claims:
            assert claim.evidence_ids
            assert set(claim.evidence_ids) <= available


def test_all_evidence_shares_the_response_snapshot(harness: Harness) -> None:
    for response in _responses(harness):
        for item in response.evidence:
            assert item.snapshot_id == response.snapshot.snapshot_id
            assert item.repository_id == response.repository_id


def test_derivation_and_confidence_remain_distinct_fields(harness: Harness) -> None:
    for response in _responses(harness):
        for item in response.evidence:
            assert item.derivation in _LEXICAL_DERIVATIONS
            assert 0.0 <= item.confidence <= 1.0
        for claim in response.answer.claims:
            assert claim.derivation in _LEXICAL_DERIVATIONS
            assert 0.0 <= claim.confidence <= 1.0


def test_evidence_line_ranges_are_positive_and_ordered(harness: Harness) -> None:
    for response in _responses(harness):
        for item in response.evidence:
            assert 1 <= item.start_line <= item.end_line


def test_every_response_declares_its_limitations(harness: Harness) -> None:
    for response in _responses(harness):
        assert response.limitations
        assert response.request_id


def test_no_response_leaks_the_repository_root(harness: Harness) -> None:
    root = str(harness.root)
    variants = {root, root.replace("\\", "/"), root.replace("/", "\\")}

    for response in _responses(harness):
        serialized = response.model_dump_json()
        for variant in variants:
            assert variant not in serialized
        for item in response.evidence:
            assert not Path(item.file_path).is_absolute()
