"""A minimal, valid SARIF 2.1.0 export of one change analysis.

SARIF is an export format, never the internal model. The mapping is deliberately
conservative: only fields whose meaning is unambiguous in the standard are
emitted, and every CodeAtlas-specific fact that has no SARIF equivalent —
derivation, confidence, the side a citation came from — goes in ``properties``
rather than being forced into a field that means something else.

Two rules matter for consumers:

* every ``artifactLocation`` URI is repository-relative, so a report can be read
  on a machine that is not the one that produced it and cannot leak a local
  absolute path;
* a finding with no citable evidence produces no result. SARIF requires a
  location, and inventing one would be exactly the fabrication this product
  exists to prevent.
"""

from __future__ import annotations

from typing import Any, Final

from codeatlas.contracts import ChangeAnalysisReport, Finding, Severity

SARIF_VERSION: Final[str] = "2.1.0"
SARIF_SCHEMA: Final[str] = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/"
    "sarif-schema-2.1.0.json"
)
TOOL_NAME: Final[str] = "CodeAtlas"

# SARIF has three result levels plus `none`. `critical` and `high` both map to
# `error` because SARIF draws no finer distinction; the original severity is
# preserved in `properties` rather than lost in the translation.
_LEVEL: Final[dict[Severity, str]] = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def render_sarif(report: ChangeAnalysisReport) -> dict[str, Any]:
    """Render one persisted analysis as a SARIF 2.1.0 log."""
    evidence = {item.evidence_id: item for item in report.evidence}
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for finding in report.findings:
        rules.setdefault(finding.code, _rule(finding))
        locations = [
            _location(evidence[evidence_id])
            for evidence_id in finding.evidence_ids
            if evidence_id in evidence
        ]
        if not locations:
            # SARIF requires a location. A result without one would be a claim
            # nobody can check.
            continue
        results.append(
            {
                "ruleId": finding.code,
                "level": _LEVEL[finding.severity],
                "message": {"text": finding.description},
                "locations": locations,
                "partialFingerprints": {
                    "codeatlasEvidence/v1": finding.evidence_ids[0],
                },
                "properties": {
                    "severity": finding.severity.value,
                    "derivation": finding.derivation.value,
                    "confidence": finding.confidence,
                    "limitations": list(finding.limitations),
                },
            }
        )

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "informationUri": "https://localhost/codeatlas",
                        "rules": [rules[code] for code in sorted(rules)],
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "toolExecutionNotifications": [
                            {"message": {"text": warning}}
                            for warning in report.warnings
                        ],
                    }
                ],
                "properties": {
                    "analysisId": report.analysis_id,
                    "repositoryId": report.repository_id,
                    "kind": report.kind.value,
                    "overallRisk": report.overall_risk.value,
                    "baseRef": report.base.ref,
                    "targetRef": report.target.ref,
                    "limitations": list(report.limitations),
                    "testGaps": list(report.test_gaps),
                },
            }
        ],
    }


def _rule(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.code,
        "name": finding.code,
        "shortDescription": {"text": finding.title},
        "fullDescription": {"text": finding.description},
        "defaultConfiguration": {"level": _LEVEL[finding.severity]},
        "properties": {"derivation": finding.derivation.value},
    }


def _location(item: Any) -> dict[str, Any]:
    return {
        "physicalLocation": {
            # Relative by construction: `RepositoryRelativePath` is validated at
            # the contract boundary, so no absolute path can reach here.
            "artifactLocation": {"uri": item.file_path, "uriBaseId": "%SRCROOT%"},
            "region": {
                "startLine": item.start_line,
                "endLine": item.end_line,
            },
        },
        "properties": {"side": item.side.value, "symbol": item.symbol},
    }
