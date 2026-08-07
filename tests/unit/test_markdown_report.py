"""The audit rendering of one change analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from codeatlas.contracts import (
    AnalysisSide,
    AnalysisStateRef,
    ChangeAnalysisKind,
    ChangeAnalysisReport,
    ChangeAnalysisStatus,
    ChangeEvidenceItem,
    Derivation,
    GapReason,
    GapReasonCode,
    OverallRisk,
    SnapshotFreshness,
)
from codeatlas.delivery import render_markdown


def _state(ref: str) -> AnalysisStateRef:
    return AnalysisStateRef(
        ref=ref,
        commit="a1b2c3d",
        freshness=SnapshotFreshness.FRESH,
        snapshot_id=None,
    )


def _evidence(evidence_id: str = "e1") -> ChangeEvidenceItem:
    return ChangeEvidenceItem(
        evidence_id=evidence_id,
        side=AnalysisSide.TARGET,
        file_path="src/orders.py",
        symbol=None,
        start_line=1,
        end_line=2,
        content_hash="h",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _report(**overrides: Any) -> ChangeAnalysisReport:
    fields: dict[str, Any] = {
        "analysis_id": "a1",
        "repository_id": "r1",
        "request_id": "q1",
        "kind": ChangeAnalysisKind.WORKING_TREE,
        "status": ChangeAnalysisStatus.COMPLETED,
        "overall_risk": OverallRisk.LOW,
        "base": _state("HEAD"),
        "target": _state("working-tree"),
        "created_at": datetime(2026, 8, 7, tzinfo=UTC),
    }
    fields.update(overrides)
    return ChangeAnalysisReport(**fields)


def test_a_gap_carries_its_reason_and_explanation() -> None:
    markdown = render_markdown(
        _report(
            test_gaps=["orders.Order"],
            test_gap_reasons=[
                GapReason(
                    qualified_name="orders.Order",
                    reason=GapReasonCode.FIXTURE_MEDIATED_ONLY,
                    explanation="A test reaches this only through a fixture.",
                    evidence_ids=[],
                )
            ],
        )
    )

    assert "orders.Order" in markdown
    assert "FIXTURE_MEDIATED_ONLY" in markdown
    assert "only through a fixture" in markdown


def test_a_gap_with_no_reason_still_appears() -> None:
    # The name is a real finding of the analysis even when no reason
    # accompanied it. Dropping it would under-report the gap list.
    markdown = render_markdown(_report(test_gaps=["orders.Order"]))

    assert "orders.Order" in markdown


def test_the_disclaimer_is_present_whenever_a_gap_is() -> None:
    markdown = render_markdown(_report(test_gaps=["orders.Order"]))

    assert "does not prove absence of coverage" in markdown
    assert "does not execute tests" in markdown


def test_a_gap_reason_cites_its_evidence() -> None:
    markdown = render_markdown(
        _report(
            test_gaps=["orders.Order"],
            test_gap_reasons=[
                GapReason(
                    qualified_name="orders.Order",
                    reason=GapReasonCode.FIXTURE_MEDIATED_ONLY,
                    explanation="Reached through a fixture.",
                    evidence_ids=["e1"],
                )
            ],
            evidence=[_evidence()],
        )
    )

    assert "src/orders.py" in markdown


def test_a_hostile_gap_name_is_escaped() -> None:
    markdown = render_markdown(_report(test_gaps=["a|b`c"]))

    assert "a\\|b\\`c" in markdown


def test_the_severity_ordering_lives_in_one_place() -> None:
    """Three renderers and --fail-on all rank severity.

    Copies of "which severity is worse" are places for them to disagree.
    """
    from codeatlas.contracts import SEVERITY_ORDER, Severity

    assert SEVERITY_ORDER == (
        Severity.CRITICAL,
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
        Severity.INFO,
    )
