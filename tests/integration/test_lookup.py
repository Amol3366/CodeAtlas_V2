"""Exact symbol lookup, freshness, abstention, status, and diagnostics."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.lookup import MAX_QUERY_LENGTH, SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import (
    Derivation,
    EvidenceValidation,
    SnapshotFreshness,
)
from codeatlas.domain.errors import (
    InvalidRequestError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@dataclass
class Indexed:
    services: ApplicationServices
    repository_id: str
    snapshot_id: str
    root: Path


@pytest.fixture()
def services(tmp_path: Path) -> Iterator[ApplicationServices]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        yield build_services(connection)


@pytest.fixture()
def indexed(services: ApplicationServices, sample_repo: Path) -> Indexed:
    repository = services.registration.register(
        RegisterRepositoryRequest(path=str(sample_repo))
    )
    result = services.indexing.index(repository.repository_id)
    return Indexed(
        services=services,
        repository_id=repository.repository_id,
        snapshot_id=result.snapshot.snapshot_id,
        root=sample_repo,
    )


def test_exact_lookup_returns_validated_snapshot_bound_evidence(
    indexed: Indexed,
) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="PaymentService.capture",
            request_id="req-1",
        )
    )

    assert response.contract_version == "1.1"
    assert response.repository_id == indexed.repository_id
    assert response.snapshot.snapshot_id == indexed.snapshot_id
    assert response.snapshot.freshness is SnapshotFreshness.FRESH

    evidence = response.evidence[0]
    assert evidence.file_path == "src/payments/service.py"
    assert (evidence.start_line, evidence.end_line) == (7, 8)
    assert evidence.symbol == "PaymentService.capture"
    assert evidence.derivation is Derivation.DETERMINISTIC
    assert evidence.validation is EvidenceValidation.VALID
    assert "def capture" in evidence.excerpt

    claim = response.answer.claims[0]
    assert claim.derivation is Derivation.STATIC_RESOLVED
    assert claim.evidence_ids == [evidence.evidence_id]
    assert "src/payments/service.py" in claim.text


def test_lookup_resolves_a_class_definition(indexed: Indexed) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="PaymentService",
            request_id="req-class",
        )
    )
    evidence = response.evidence[0]
    assert (evidence.start_line, evidence.end_line) == (3, 8)


def test_bare_name_and_case_insensitive_lookup_resolve(indexed: Indexed) -> None:
    for query in ("capture", "CAPTURE"):
        response = indexed.services.lookup.lookup(
            SymbolLookupRequest(
                repository_id=indexed.repository_id,
                query=query,
                request_id="req-2",
            )
        )
        assert response.evidence[0].symbol == "PaymentService.capture"


def test_unknown_symbol_abstains_without_inventing_evidence(indexed: Indexed) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="NoSuchSymbol",
            request_id="req-3",
        )
    )
    assert response.answer.claims == []
    assert response.evidence == []
    assert "NO_EXACT_SYMBOL_MATCH" in response.warnings
    assert "NoSuchSymbol" in response.answer.summary


def test_modified_file_after_indexing_is_reported_stale_and_not_cited(
    indexed: Indexed,
) -> None:
    path = indexed.root / "src" / "payments" / "service.py"
    path.write_text("# edited\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="PaymentService.capture",
            request_id="req-4",
        )
    )
    assert response.snapshot.freshness is SnapshotFreshness.STALE
    assert response.evidence == []
    assert response.answer.claims == []
    assert "EVIDENCE_STALE_FILE_CONTENT" in response.warnings


def test_deleted_file_after_indexing_does_not_produce_evidence(
    indexed: Indexed,
) -> None:
    (indexed.root / "src" / "payments" / "service.py").unlink()
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="PaymentService.capture",
            request_id="req-5",
        )
    )
    assert response.evidence == []
    assert "EVIDENCE_FILE_UNREADABLE" in response.warnings


def test_lookup_without_an_active_snapshot_raises(
    services: ApplicationServices, sample_repo: Path
) -> None:
    repository = services.registration.register(
        RegisterRepositoryRequest(path=str(sample_repo))
    )
    with pytest.raises(SnapshotNotReadyError):
        services.lookup.lookup(
            SymbolLookupRequest(
                repository_id=repository.repository_id,
                query="PaymentService",
                request_id="req-6",
            )
        )


def test_lookup_for_an_unknown_repository_raises(
    services: ApplicationServices,
) -> None:
    with pytest.raises(RepositoryNotFoundError):
        services.lookup.lookup(
            SymbolLookupRequest(
                repository_id="repo_missing",
                query="PaymentService",
                request_id="req-7",
            )
        )


@pytest.mark.parametrize("query", ["", "   ", "x" * (MAX_QUERY_LENGTH + 1)])
def test_invalid_queries_are_rejected(indexed: Indexed, query: str) -> None:
    with pytest.raises(InvalidRequestError):
        indexed.services.lookup.lookup(
            SymbolLookupRequest(
                repository_id=indexed.repository_id,
                query=query,
                request_id="req-8",
            )
        )


def test_timing_is_recorded(indexed: Indexed) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="PaymentService",
            request_id="req-9",
        )
    )
    assert {"lookup", "evidence"} <= set(response.timing_ms)


def test_limitations_declare_the_phase_boundary(indexed: Indexed) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=indexed.repository_id,
            query="PaymentService",
            request_id="req-10",
        )
    )
    assert any("Phase 1" in limitation for limitation in response.limitations)


def test_status_reports_the_active_snapshot_and_counts(indexed: Indexed) -> None:
    status = indexed.services.status.status(indexed.repository_id)
    assert status.snapshot is not None
    assert status.snapshot.snapshot_id == indexed.snapshot_id
    assert status.file_count == 3
    assert status.symbol_count > 0
    assert status.parse_error_count == 0


def test_status_before_indexing_reports_no_snapshot(
    services: ApplicationServices, sample_repo: Path
) -> None:
    repository = services.registration.register(
        RegisterRepositoryRequest(path=str(sample_repo))
    )
    status = services.status.status(repository.repository_id)
    assert status.snapshot is None
    assert status.file_count == 0
    assert "SNAPSHOT_NOT_READY" in status.warnings


def test_diagnostics_report_skipped_reasons_and_limits(
    services: ApplicationServices, sample_repo: Path
) -> None:
    (sample_repo / "blob.bin").write_bytes(b"ok\x00binary")
    repository = services.registration.register(
        RegisterRepositoryRequest(path=str(sample_repo))
    )
    services.indexing.index(repository.repository_id)

    diagnostics = services.status.diagnostics(repository.repository_id)
    assert diagnostics.snapshot_id is not None
    assert diagnostics.limits.max_file_bytes > 0
    assert diagnostics.skipped_by_reason.get("BINARY", 0) >= 1


def test_status_for_an_unknown_repository_raises(
    services: ApplicationServices,
) -> None:
    with pytest.raises(RepositoryNotFoundError):
        services.status.status("repo_missing")
