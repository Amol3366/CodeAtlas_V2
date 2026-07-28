from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    ErrorDetail,
    ErrorEnvelope,
    Evidence,
    EvidenceValidation,
    QueryResponse,
    SnapshotFreshness,
    SnapshotReference,
    StreamEventMetadata,
)


def valid_response_data() -> dict[str, object]:
    return {
        "contract_version": "1.1",
        "request_id": "req-1",
        "repository_id": "repo-1",
        "snapshot": {
            "snapshot_id": "snap-1",
            "git_head": "abc123",
            "working_tree_fingerprint": "tree-1",
            "freshness": "fresh",
            "semantic_coverage": 0.0,
        },
        "answer": {
            "summary": "PaymentService.capture is defined in the service module.",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "PaymentService.capture is defined on line 10.",
                    "derivation": "static_resolved",
                    "confidence": 0.99,
                    "evidence_ids": ["evidence-1"],
                }
            ],
        },
        "evidence": [
            {
                "evidence_id": "evidence-1",
                "repository_id": "repo-1",
                "snapshot_id": "snap-1",
                "file_path": "src/payments/service.py",
                "symbol": "PaymentService.capture",
                "start_line": 10,
                "end_line": 12,
                "excerpt": "def capture(self): ...",
                "content_hash": "sha256:1234",
                "derivation": "static_resolved",
                "confidence": 0.99,
                "validation": "valid",
            }
        ],
        # Added in Phase 3 (ADR-0004). Additive and optional, so
        # `contract_version` stays "1.0"; it serializes as an empty list for
        # every response that carries no relation path.
        "relation_paths": [],
        "warnings": [],
        "limitations": [],
        "timing_ms": {"total": 4.5},
    }


def test_valid_query_response_round_trips_as_contract_v1() -> None:
    response = QueryResponse.model_validate(valid_response_data())

    assert response.contract_version == "1.1"
    assert response.snapshot.freshness is SnapshotFreshness.FRESH
    assert response.answer.claims[0].derivation is Derivation.STATIC_RESOLVED
    assert response.evidence[0].validation is EvidenceValidation.VALID
    assert response.model_dump(mode="json") == valid_response_data()


@pytest.mark.parametrize(
    ("field_path", "bad_value"),
    [
        (("evidence", 0, "file_path"), "../secrets.txt"),
        (("evidence", 0, "file_path"), "C:/secrets.txt"),
        (("evidence", 0, "file_path"), r"src\payments\service.py"),
        (("evidence", 0, "file_path"), "src/data.txt:secret"),
        (("evidence", 0, "file_path"), "src/CON.txt"),
        (("evidence", 0, "file_path"), "src/control\u0001.py"),
        (("evidence", 0, "file_path"), "src/cafe\u0301.py"),
        (("evidence", 0, "start_line"), 0),
        (("evidence", 0, "confidence"), 1.01),
        (("snapshot", "semantic_coverage"), -0.01),
    ],
)
def test_query_response_rejects_unsafe_or_out_of_range_values(
    field_path: tuple[str | int, ...],
    bad_value: object,
) -> None:
    data = deepcopy(valid_response_data())
    target: object = data
    for part in field_path[:-1]:
        target = target[part]  # type: ignore[index]
    target[field_path[-1]] = bad_value  # type: ignore[index]

    with pytest.raises(ValidationError):
        QueryResponse.model_validate(data)


def test_evidence_rejects_reversed_line_range() -> None:
    data = deepcopy(valid_response_data())
    evidence = data["evidence"][0]  # type: ignore[index]
    evidence["start_line"] = 20
    evidence["end_line"] = 10

    with pytest.raises(ValidationError, match="end_line"):
        QueryResponse.model_validate(data)


@pytest.mark.parametrize(
    ("field_path", "bad_value", "message"),
    [
        (("answer", "claims", 0, "evidence_ids"), ["invented"], "unknown evidence"),
        (("evidence", 0, "repository_id"), "repo-2", "repository"),
        (("evidence", 0, "snapshot_id"), "snap-2", "snapshot"),
        (("evidence", 0, "validation"), "invalid", "valid evidence"),
    ],
)
def test_query_response_rejects_untrusted_evidence_links(
    field_path: tuple[str | int, ...],
    bad_value: object,
    message: str,
) -> None:
    data = deepcopy(valid_response_data())
    target: object = data
    for part in field_path[:-1]:
        target = target[part]  # type: ignore[index]
    target[field_path[-1]] = bad_value  # type: ignore[index]

    with pytest.raises(ValidationError, match=message):
        QueryResponse.model_validate(data)


def test_claim_requires_at_least_one_evidence_id() -> None:
    with pytest.raises(ValidationError):
        Claim(
            claim_id="claim-1",
            text="A material factual claim",
            derivation=Derivation.DETERMINISTIC,
            confidence=1.0,
            evidence_ids=[],
        )


def test_contract_models_reject_unknown_fields() -> None:
    data = valid_response_data()
    data["invented"] = True

    with pytest.raises(ValidationError, match="Extra inputs"):
        QueryResponse.model_validate(data)


def test_duplicate_evidence_ids_are_rejected() -> None:
    data = valid_response_data()
    data["evidence"] = [data["evidence"][0], deepcopy(data["evidence"][0])]  # type: ignore[index]

    with pytest.raises(ValidationError, match="unique"):
        QueryResponse.model_validate(data)


def test_error_envelope_uses_stable_machine_readable_shape() -> None:
    error = ErrorEnvelope(
        error=ErrorDetail(
            code="SNAPSHOT_NOT_READY",
            message="The repository snapshot is not ready.",
            request_id="req-1",
            retryable=True,
            details={},
        )
    )

    assert error.model_dump(mode="json") == {
        "error": {
            "code": "SNAPSHOT_NOT_READY",
            "message": "The repository snapshot is not ready.",
            "request_id": "req-1",
            "retryable": True,
            "details": {},
        }
    }


def test_individual_contract_models_are_strict() -> None:
    snapshot = SnapshotReference(
        snapshot_id="snap-1",
        git_head=None,
        working_tree_fingerprint="tree-1",
        freshness=SnapshotFreshness.UNKNOWN,
        semantic_coverage=0.0,
    )
    evidence = Evidence.model_validate(valid_response_data()["evidence"][0])  # type: ignore[index]
    answer = Answer(
        summary="Verified answer.",
        claims=[
            Claim(
                claim_id="claim-1",
                text="Verified claim.",
                derivation=Derivation.STATIC_RESOLVED,
                confidence=0.9,
                evidence_ids=["evidence-1"],
            )
        ],
    )

    assert snapshot.snapshot_id == "snap-1"
    assert evidence.file_path == "src/payments/service.py"
    assert answer.claims[0].claim_id == "claim-1"


def test_stream_metadata_requires_an_explicit_utc_timestamp() -> None:
    valid = StreamEventMetadata(
        request_id="req-1",
        conversation_id="conversation-1",
        message_id="message-1",
        sequence=1,
        timestamp=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
    )
    assert valid.timestamp.isoformat() == "2026-07-25T12:00:00+00:00"

    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        StreamEventMetadata(
            request_id="req-1",
            conversation_id="conversation-1",
            message_id="message-1",
            sequence=1,
            timestamp=datetime(2026, 7, 25, 12, 0),
        )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        StreamEventMetadata(
            request_id="req-1",
            conversation_id="conversation-1",
            message_id="message-1",
            sequence=1,
            timestamp=datetime(
                2026,
                7,
                25,
                12,
                0,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
        )
