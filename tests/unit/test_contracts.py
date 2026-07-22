"""Phase 0 contract tests: enums and the shared evidence/response schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeatlas.contracts import Claim, EvidenceItem, Finding, QueryResponse, Scope
from codeatlas.domain.enums import (
    Derivation,
    EvidenceKind,
    FindingCategory,
    IntentType,
    RelationType,
    Severity,
    SymbolType,
)


def test_symbol_and_relation_enums_are_fixed() -> None:
    # Blueprint §4.4.6 lists 20 symbol types; §4.4.7 lists 17 relation types.
    assert len(list(SymbolType)) == 20
    assert len(list(RelationType)) == 17
    # The sacred distinction (CLAUDE.md §2.11) exists.
    assert RelationType.CALLS != RelationType.MAY_CALL


def _evidence(**overrides: object) -> EvidenceItem:
    base: dict[str, object] = dict(
        id="evidence_01",
        snapshot_id="snapshot_019",
        kind=EvidenceKind.CODE,
        file_path="src/api/partner_payments.py",
        symbol="capture_partner_payment",
        start_line=42,
        end_line=68,
        relation_path=["capture_partner_payment", "CALLS", "PaymentService.capture"],
        confidence=0.98,
        derivation=Derivation.STATIC_RESOLVED,
    )
    base.update(overrides)
    return EvidenceItem(**base)  # type: ignore[arg-type]


def test_query_response_roundtrips() -> None:
    scope = Scope(repository_id="repo_001", snapshot_id="snapshot_019", branch="main")
    ev = _evidence()
    response = QueryResponse(
        answer="The partner payment endpoint calls PaymentService.capture.",
        confidence=0.87,
        intent=IntentType.IMPACT_ANALYSIS,
        scope=scope,
        claims=[Claim(text="It calls capture.", confidence=0.98, evidence_ids=["evidence_01"])],
        evidence=[ev],
        warnings=["One dynamic call could not be resolved."],
    )
    dumped = response.model_dump_json()
    reloaded = QueryResponse.model_validate_json(dumped)
    assert reloaded == response
    assert reloaded.evidence[0].derivation is Derivation.STATIC_RESOLVED


def test_contract_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Scope(repository_id="r", snapshot_id="s", bogus="x")  # type: ignore[call-arg]


def test_contract_models_are_frozen() -> None:
    ev = _evidence()
    with pytest.raises(ValidationError):
        ev.confidence = 0.1  # type: ignore[misc]


def test_confidence_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        _evidence(confidence=1.5)


def test_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Claim(text="unsupported", confidence=0.5, evidence_ids=[])


def test_finding_records_determinism() -> None:
    finding = Finding(
        id="finding_01",
        category=FindingCategory.CONTRACT_CHANGE,
        severity=Severity.HIGH,
        title="Public signature changed",
        description="capture gained a required parameter.",
        confidence=1.0,
        deterministic=True,
        derivation=Derivation.STATIC_RESOLVED,
        evidence_ids=["evidence_01"],
    )
    assert finding.deterministic is True
