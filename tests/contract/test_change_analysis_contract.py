from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from codeatlas.contracts import (
    AnalysisSide,
    AnalysisStateRef,
    ChangeAnalysisKind,
    ChangeAnalysisReport,
    ChangeAnalysisStatus,
    ChangedFile,
    ChangedSymbol,
    ChangeEvidenceItem,
    ChangeKind,
    Derivation,
    FileChangeKind,
    Finding,
    ImpactEdge,
    OverallRisk,
    RelationKind,
    Severity,
    SnapshotFreshness,
    SymbolKind,
)


def valid_report_data() -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "analysis_id": "ca_abc",
        "request_id": "req-1",
        "repository_id": "repo_1",
        "kind": "working_tree",
        "status": "completed",
        "overall_risk": "medium",
        "base": {
            "ref": "HEAD",
            "commit": "0" * 40,
            "snapshot_id": None,
            "freshness": "fresh",
        },
        "target": {
            "ref": "working-tree",
            "commit": None,
            "snapshot_id": "snap_current",
            "freshness": "fresh",
        },
        "changed_files": [
            {
                "path": "src/service.py",
                "change_kind": "modified",
                "base_path": None,
                "content_hash_changed": False,
            }
        ],
        "changed_symbols": [
            {
                "qualified_name": "PaymentService.capture",
                "symbol_kind": "METHOD",
                "change_kind": "modified",
                "file_path": "src/service.py",
                "base_file_path": None,
                "base_start_line": None,
                "base_end_line": None,
                "target_start_line": 7,
                "target_end_line": 11,
                "signature_changed": False,
                "public": True,
                "derivation": "high_confidence_heuristic",
                "confidence": 0.7,
            }
        ],
        "impact_edges": [
            {
                "source": "PaymentService.capture",
                "target": "test_capture",
                "kind": "TESTS",
                "derivation": "high_confidence_heuristic",
                "confidence": 0.7,
            }
        ],
        "findings": [
            {
                "code": "PUBLIC_BEHAVIOR_CHANGED",
                "severity": "medium",
                "title": "capture changed",
                "description": (
                    "The body of capture changed without a signature change."
                ),
                "derivation": "high_confidence_heuristic",
                "confidence": 0.7,
                "evidence_ids": ["cev_1"],
                "remediation": None,
                "limitations": [],
            }
        ],
        "evidence": [
            {
                "evidence_id": "cev_1",
                "side": "target",
                "file_path": "src/service.py",
                "symbol": "PaymentService.capture",
                "start_line": 7,
                "end_line": 11,
                "content_hash": "sha256:abc",
                "derivation": "high_confidence_heuristic",
                "confidence": 0.7,
            }
        ],
        "test_gaps": [],
        "warnings": [],
        "limitations": ["Phase 4 resolves relations statically."],
        "timing_ms": {"total": 1.25},
        "created_at": "2026-07-26T12:00:00Z",
        "completed_at": "2026-07-26T12:00:01Z",
    }


def test_valid_report_round_trips_as_contract_v1() -> None:
    report = ChangeAnalysisReport.model_validate(valid_report_data())

    assert report.contract_version == "1.0"
    assert report.kind is ChangeAnalysisKind.WORKING_TREE
    assert report.status is ChangeAnalysisStatus.COMPLETED
    assert report.overall_risk is OverallRisk.MEDIUM
    assert report.base.freshness is SnapshotFreshness.FRESH
    assert report.target.snapshot_id == "snap_current"
    assert report.changed_symbols[0].change_kind is ChangeKind.MODIFIED
    assert report.changed_symbols[0].derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
    assert report.impact_edges[0].kind == "TESTS"
    assert report.evidence[0].side is AnalysisSide.TARGET
    # The model is frozen and forbids unknown fields, so the round-trip is exact.
    assert report.model_dump(mode="json") == valid_report_data()


def test_report_rejects_unknown_fields() -> None:
    data = valid_report_data()
    data["invented"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        ChangeAnalysisReport.model_validate(data)


def test_report_rejects_evidence_from_the_wrong_repository() -> None:
    # Findings cite evidence by ID. An evidence ID a finding names but the
    # report does not list is an unverifiable claim, exactly as in QueryResponse.
    data = deepcopy(valid_report_data())
    data["findings"][0]["evidence_ids"] = ["cev_invented"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="unknown evidence"):
        ChangeAnalysisReport.model_validate(data)


def test_report_rejects_duplicate_evidence_ids() -> None:
    data = deepcopy(valid_report_data())
    data["evidence"] = [data["evidence"][0], deepcopy(data["evidence"][0])]  # type: ignore[index]
    with pytest.raises(ValidationError, match="unique"):
        ChangeAnalysisReport.model_validate(data)


def test_report_rejects_an_unsafe_evidence_path() -> None:
    data = deepcopy(valid_report_data())
    data["evidence"][0]["file_path"] = "../../etc/passwd"  # type: ignore[index]
    with pytest.raises(ValidationError):
        ChangeAnalysisReport.model_validate(data)


def test_report_rejects_a_reversed_evidence_line_range() -> None:
    data = deepcopy(valid_report_data())
    data["evidence"][0]["start_line"] = 20  # type: ignore[index]
    data["evidence"][0]["end_line"] = 10  # type: ignore[index]
    with pytest.raises(ValidationError, match="end_line"):
        ChangeAnalysisReport.model_validate(data)


def test_report_rejects_an_out_of_range_confidence() -> None:
    data = deepcopy(valid_report_data())
    data["changed_symbols"][0]["confidence"] = 1.5  # type: ignore[index]
    with pytest.raises(ValidationError):
        ChangeAnalysisReport.model_validate(data)


def test_report_rejects_an_empty_changed_files_list_when_symbols_changed() -> None:
    # If symbols changed, files changed; an empty list alongside a non-empty
    # changed-symbol set is a contradiction the contract should not allow.
    data = deepcopy(valid_report_data())
    data["changed_files"] = []
    with pytest.raises(ValidationError, match="changed_files"):
        ChangeAnalysisReport.model_validate(data)


def test_state_ref_allows_no_snapshot_on_the_base_side() -> None:
    base = AnalysisStateRef(
        ref="HEAD",
        commit="0" * 40,
        snapshot_id=None,
        freshness=SnapshotFreshness.FRESH,
    )
    target = AnalysisStateRef(
        ref="working-tree",
        commit=None,
        snapshot_id="snap_current",
        freshness=SnapshotFreshness.FRESH,
    )
    assert base.snapshot_id is None
    assert target.snapshot_id == "snap_current"


def test_changed_symbol_rejects_base_lines_without_a_base_file() -> None:
    # A deleted symbol carries base lines and a base path; a modified symbol
    # carries target lines. Mixing the two is a contract violation.
    with pytest.raises(ValidationError, match="base_start_line"):
        ChangedSymbol(
            qualified_name="gone",
            symbol_kind=SymbolKind.FUNCTION,
            change_kind=ChangeKind.DELETED,
            file_path="src/gone.py",
            base_file_path=None,
            base_start_line=4,
            base_end_line=None,
            target_start_line=None,
            target_end_line=None,
            signature_changed=False,
            public=True,
            derivation=Derivation.DETERMINISTIC,
            confidence=1.0,
        )


def test_overall_risk_includes_a_none_value() -> None:
    assert OverallRisk.NONE.value == "none"


def test_impact_edge_carries_no_evidence_id_by_design() -> None:
    # An impact edge is a labeled graph fact, not a citable region. Keeping
    # evidence off the edge is what protects the exact/containing metrics.
    edge = ImpactEdge(
        source="a",
        target="b",
        kind=RelationKind.CALLS,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
    )
    dumped = edge.model_dump(mode="json")
    assert "evidence_id" not in dumped
    assert set(dumped) == {"source", "target", "kind", "derivation", "confidence"}


def test_change_evidence_item_requires_a_side() -> None:
    with pytest.raises(ValidationError):
        ChangeEvidenceItem(  # type: ignore[call-arg]
            evidence_id="cev_1",
            file_path="src/service.py",
            symbol="capture",
            start_line=7,
            end_line=11,
            content_hash="sha256:abc",
            derivation=Derivation.DETERMINISTIC,
            confidence=1.0,
        )


def test_finding_is_reused_unchanged() -> None:
    # Phase 4 reuses the existing Finding contract; it must round-trip here.
    finding = Finding(
        code="SYMBOL_DELETED",
        severity=Severity.HIGH,
        title="gone",
        description="The symbol was removed.",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
        evidence_ids=["cev_1"],
    )
    assert finding.severity is Severity.HIGH


def test_report_timestamp_must_be_utc() -> None:
    data = deepcopy(valid_report_data())
    data["created_at"] = "2026-07-26T12:00:00+05:30"
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ChangeAnalysisReport.model_validate(data)


def test_constructed_report_round_trips() -> None:
    # Constructing the report from typed models (not dicts) must also produce a
    # byte-identical dump, proving the models compose without surprise defaults.
    report = ChangeAnalysisReport(
        contract_version="1.0",
        analysis_id="ca_abc",
        request_id="req-1",
        repository_id="repo_1",
        kind=ChangeAnalysisKind.WORKING_TREE,
        status=ChangeAnalysisStatus.COMPLETED,
        overall_risk=OverallRisk.MEDIUM,
        base=AnalysisStateRef(
            ref="HEAD",
            commit="0" * 40,
            snapshot_id=None,
            freshness=SnapshotFreshness.FRESH,
        ),
        target=AnalysisStateRef(
            ref="working-tree",
            commit=None,
            snapshot_id="snap_current",
            freshness=SnapshotFreshness.FRESH,
        ),
        changed_files=[
            ChangedFile(
                path="src/service.py",
                change_kind=FileChangeKind.MODIFIED,
                base_path=None,
                content_hash_changed=False,
            )
        ],
        changed_symbols=[
            ChangedSymbol(
                qualified_name="PaymentService.capture",
                symbol_kind=SymbolKind.METHOD,
                change_kind=ChangeKind.MODIFIED,
                file_path="src/service.py",
                base_file_path=None,
                base_start_line=None,
                base_end_line=None,
                target_start_line=7,
                target_end_line=11,
                signature_changed=False,
                public=True,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=0.7,
            )
        ],
        impact_edges=[
            ImpactEdge(
                source="PaymentService.capture",
                target="test_capture",
                kind=RelationKind.TESTS,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=0.7,
            )
        ],
        findings=[
            Finding(
                code="PUBLIC_BEHAVIOR_CHANGED",
                severity=Severity.MEDIUM,
                title="capture changed",
                description="The body of capture changed without a signature change.",
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=0.7,
                evidence_ids=["cev_1"],
            )
        ],
        evidence=[
            ChangeEvidenceItem(
                evidence_id="cev_1",
                side=AnalysisSide.TARGET,
                file_path="src/service.py",
                symbol="PaymentService.capture",
                start_line=7,
                end_line=11,
                content_hash="sha256:abc",
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=0.7,
            )
        ],
        test_gaps=[],
        warnings=[],
        limitations=["Phase 4 resolves relations statically."],
        timing_ms={"total": 1.25},
        created_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 26, 12, 0, 1, tzinfo=UTC),
    )
    assert report.model_dump(mode="json") == valid_report_data()