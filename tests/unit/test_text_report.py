"""The terminal rendering of one change analysis."""

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
    Finding,
    GapReason,
    GapReasonCode,
    ImpactEdge,
    OverallRisk,
    RelationKind,
    Severity,
    SnapshotFreshness,
)
from codeatlas.delivery import render_text


def _state(ref: str) -> AnalysisStateRef:
    return AnalysisStateRef(
        ref=ref,
        commit="a1b2c3d",
        freshness=SnapshotFreshness.FRESH,
        snapshot_id=None,
    )


def _evidence(index: int = 1) -> ChangeEvidenceItem:
    return ChangeEvidenceItem(
        evidence_id=f"e{index}",
        side=AnalysisSide.TARGET,
        file_path="src/orders.py",
        symbol=None,
        start_line=40,
        end_line=52,
        content_hash="h",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _finding(severity: Severity, title: str) -> Finding:
    # evidence_ids has min_length=1 and every id must exist in report.evidence.
    return Finding(
        code="PUBLIC_CONTRACT_CHANGED",
        severity=severity,
        title=title,
        description="The signature changed.",
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.9,
        evidence_ids=["e1"],
    )


def _edge(
    derivation: Derivation = Derivation.STATIC_RESOLVED,
) -> ImpactEdge:
    return ImpactEdge(
        source="orders.Order.total",
        kind=RelationKind.CALLS,
        target="api.checkout",
        derivation=derivation,
        confidence=0.9,
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
        "created_at": datetime(2026, 8, 8, tzinfo=UTC),
    }
    fields.update(overrides)
    return ChangeAnalysisReport(**fields)


def _with_findings(*findings: Finding, **overrides: Any) -> ChangeAnalysisReport:
    return _report(findings=list(findings), evidence=[_evidence(1)], **overrides)


def test_the_verdict_is_the_first_line() -> None:
    text = render_text(_report(overall_risk=OverallRisk.HIGH))

    assert text.splitlines()[0].startswith("HIGH risk")


def test_severity_is_a_word_not_a_colour() -> None:
    # documentation/design.md: colour is never the only signal. The simplest
    # way to satisfy that in a terminal is not to depend on colour at all.
    text = render_text(_with_findings(_finding(Severity.HIGH, "T")))

    assert "HIGH" in text
    assert "\x1b[" not in text


def test_no_ansi_escape_appears_anywhere() -> None:
    text = render_text(
        _with_findings(_finding(Severity.CRITICAL, "T"), test_gaps=["a"])
    )

    assert "\x1b" not in text


def test_findings_are_ordered_most_severe_first() -> None:
    text = render_text(
        _with_findings(
            _finding(Severity.LOW, "Low one"),
            _finding(Severity.CRITICAL, "Critical one"),
        )
    )

    assert text.index("Critical one") < text.index("Low one")


def test_a_finding_shows_derivation_and_confidence() -> None:
    text = render_text(_with_findings(_finding(Severity.HIGH, "T")))

    assert "static_resolved" in text
    assert "0.90" in text


def test_no_findings_is_not_a_safety_claim() -> None:
    text = render_text(_report())

    assert "not a claim that the change is safe" in text


def test_the_gap_disclaimer_is_present_whenever_a_gap_is() -> None:
    text = render_text(_report(test_gaps=["orders.Order"]))

    assert "does not prove absence of coverage" in text
    assert "does not execute tests" in text


def test_a_gap_carries_its_reason() -> None:
    text = render_text(
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

    assert "FIXTURE_MEDIATED_ONLY" in text
    assert "only through a fixture" in text


def test_a_gap_with_no_reason_still_appears() -> None:
    text = render_text(_report(test_gaps=["orders.Order"]))

    assert "orders.Order" in text


def test_impact_is_summarised_with_its_weak_count() -> None:
    # A terminal is not a document: the full edge list is what markdown is for.
    # But a weak edge must never be invisible — ADR-0016.
    text = render_text(
        _report(
            impact_edges=[
                _edge(),
                _edge(derivation=Derivation.LOW_CONFIDENCE_HEURISTIC),
            ]
        )
    )

    assert "2" in text
    assert "low_confidence_heuristic" in text


def test_no_table_pipes_are_emitted() -> None:
    text = render_text(_with_findings(_finding(Severity.HIGH, "T")))

    assert "|" not in text


def test_a_control_character_from_the_repository_is_stripped() -> None:
    # Repository text reaching a terminal could move the cursor or blank a line.
    text = render_text(_report(test_gaps=["a\x1b[2Kb"]))

    assert "\x1b" not in text
