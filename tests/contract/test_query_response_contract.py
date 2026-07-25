"""Lookup responses must satisfy the public contract, not merely resemble it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.lookup import (
    MAX_EXCERPT_CHARACTERS,
    SymbolLookupRequest,
)
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import CONTRACT_VERSION, EvidenceValidation, QueryResponse
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def response(tmp_path: Path, sample_repo: Path) -> Iterator[QueryResponse]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services: ApplicationServices = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        yield services.lookup.lookup(
            SymbolLookupRequest(
                repository_id=repository.repository_id,
                query="PaymentService.capture",
                request_id="req-contract",
            )
        )


def test_response_round_trips_through_the_contract(response: QueryResponse) -> None:
    restored = QueryResponse.model_validate_json(response.model_dump_json())
    assert restored == response
    assert restored.contract_version == CONTRACT_VERSION


def test_every_claim_resolves_to_returned_evidence(response: QueryResponse) -> None:
    known = {item.evidence_id for item in response.evidence}
    for claim in response.answer.claims:
        assert claim.evidence_ids
        assert set(claim.evidence_ids) <= known


def test_all_evidence_shares_the_response_repository_and_snapshot(
    response: QueryResponse,
) -> None:
    for item in response.evidence:
        assert item.repository_id == response.repository_id
        assert item.snapshot_id == response.snapshot.snapshot_id
        assert item.validation is EvidenceValidation.VALID


def test_evidence_ids_are_unique(response: QueryResponse) -> None:
    identifiers = [item.evidence_id for item in response.evidence]
    assert len(identifiers) == len(set(identifiers))


def test_evidence_paths_are_repository_relative(response: QueryResponse) -> None:
    for item in response.evidence:
        assert not item.file_path.startswith("/")
        assert "\\" not in item.file_path
        assert ".." not in item.file_path.split("/")


def test_excerpts_are_bounded(response: QueryResponse) -> None:
    for item in response.evidence:
        assert len(item.excerpt) <= MAX_EXCERPT_CHARACTERS


def test_line_ranges_are_ordered_and_positive(response: QueryResponse) -> None:
    for item in response.evidence:
        assert item.start_line >= 1
        assert item.end_line >= item.start_line


def test_derivation_and_confidence_remain_distinct_fields(
    response: QueryResponse,
) -> None:
    claim = response.answer.claims[0]
    evidence = response.evidence[0]
    assert claim.derivation != evidence.derivation
    assert 0.0 <= claim.confidence <= 1.0
    assert 0.0 <= evidence.confidence <= 1.0
