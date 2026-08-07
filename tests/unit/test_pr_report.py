"""The pull-request rendering of one change analysis."""

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
    OverallRisk,
    Severity,
    SnapshotFreshness,
)
from codeatlas.delivery import render_pr_markdown


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
        file_path=f"src/orders_{index}.py",
        symbol=None,
        start_line=1,
        end_line=2,
        content_hash="h",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _finding(severity: Severity, title: str) -> Finding:
    # `evidence_ids` has min_length=1 and every id must exist in the report's
    # evidence, so any test using a finding must carry `_evidence(1)` too.
    return Finding(
        code="PUBLIC_CONTRACT_CHANGED",
        severity=severity,
        title=title,
        description="The signature changed.",
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.9,
        evidence_ids=["e1"],
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


def _with_findings(*findings: Finding, **overrides: Any) -> ChangeAnalysisReport:
    return _report(findings=list(findings), evidence=[_evidence(1)], **overrides)


def test_the_risk_leads_the_report() -> None:
    # The verdict is the first thing a reviewer sees, per the PRD's
    # "ordered by risk. This is the product."
    markdown = render_pr_markdown(_report(overall_risk=OverallRisk.HIGH))

    first = markdown.splitlines()[0]
    assert first.startswith("## CodeAtlas preflight")
    assert "HIGH" in first


def test_both_refs_and_their_freshness_are_stated() -> None:
    markdown = render_pr_markdown(_report())

    assert "HEAD" in markdown
    assert "fresh" in markdown


def test_findings_are_ordered_most_severe_first() -> None:
    markdown = render_pr_markdown(
        _with_findings(
            _finding(Severity.LOW, "Low one"),
            _finding(Severity.CRITICAL, "Critical one"),
        )
    )

    assert markdown.index("Critical one") < markdown.index("Low one")


def test_a_finding_shows_derivation_and_confidence_separately() -> None:
    # A high confidence score never implies a stronger derivation.
    markdown = render_pr_markdown(_with_findings(_finding(Severity.HIGH, "T")))

    assert "static_resolved" in markdown
    assert "0.90" in markdown


def test_no_findings_is_not_a_safety_claim() -> None:
    markdown = render_pr_markdown(_report())

    assert "not a claim that the change is safe" in markdown


def test_the_gap_disclaimer_is_present_whenever_a_gap_is() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "does not prove absence of coverage" in markdown
    assert "does not execute tests" in markdown


def test_the_gap_heading_says_possible_not_untested() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "Possible test gaps" in markdown


def test_a_gap_carries_its_reason_code_and_explanation() -> None:
    markdown = render_pr_markdown(
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

    assert "FIXTURE_MEDIATED_ONLY" in markdown
    assert "only through a fixture" in markdown


def test_a_gap_with_no_reason_still_appears() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "orders.Order" in markdown


def test_a_hostile_symbol_name_is_escaped() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["a|b`c"]))

    assert "a\\|b\\`c" in markdown


def test_no_forge_url_is_ever_constructed() -> None:
    # "No GitHub/GitLab or CI integration" is an explicit PRD non-goal, and a
    # guessed permalink is a citation pointing at the wrong code.
    markdown = render_pr_markdown(
        _with_findings(_finding(Severity.HIGH, "T"), test_gaps=["a"])
    )

    assert "http://" not in markdown
    assert "https://" not in markdown
