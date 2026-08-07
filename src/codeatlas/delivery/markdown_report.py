"""A human-readable rendering of one change analysis.

Everything that reaches this module came out of a repository, which means all of
it is untrusted text. A symbol named ``| --- |`` must not become a table row
separator, and a document heading containing a backtick fence must not end a
code block early. Every interpolated value is escaped for the construct it lands
in, and nothing is ever emitted raw.

The renderer adds no facts. Each section is a view of a field the report already
carries, including the ones that say what CodeAtlas could not determine —
warnings, limitations, and the test-gap list are not footnotes to be trimmed,
they are the part that keeps the rest honest.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from codeatlas.contracts import (
    ChangeAnalysisReport,
    ChangedSymbol,
    ChangeEvidenceItem,
    Finding,
    Severity,
)
from codeatlas.delivery.markdown_text import escape_cell, escape_inline, table

_SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)



def render_markdown(report: ChangeAnalysisReport) -> str:
    """Render one persisted analysis as Markdown."""
    lines: list[str] = [
        "# Change analysis",
        "",
        f"- **Analysis**: `{escape_inline(report.analysis_id)}`",
        f"- **Repository**: `{escape_inline(report.repository_id)}`",
        f"- **Kind**: {escape_inline(report.kind.value)}",
        f"- **Overall risk**: **{escape_inline(report.overall_risk.value)}**",
        f"- **Base**: `{escape_inline(report.base.ref)}`"
        f" ({escape_inline(report.base.commit or 'no commit')}, "
        f"{escape_inline(report.base.freshness.value)})",
        f"- **Target**: `{escape_inline(report.target.ref)}`"
        f" ({escape_inline(report.target.commit or 'no commit')}, "
        f"{escape_inline(report.target.freshness.value)})",
        "",
    ]

    lines += _changed_files(report)
    lines += _changed_symbols(report.changed_symbols)
    lines += _findings(report.findings, report.evidence)
    lines += _impact(report)
    lines += _test_gaps(report)
    lines += _bullets("Warnings", report.warnings)
    lines += _bullets("Limitations", report.limitations)
    lines += _evidence(report.evidence)
    return "\n".join(lines).rstrip() + "\n"


def _changed_files(report: ChangeAnalysisReport) -> list[str]:
    if not report.changed_files:
        return ["## Changed files", "", "No files differ between the two states.", ""]
    rows = [
        (
            escape_cell(item.path),
            escape_cell(item.change_kind.value),
            escape_cell(item.base_path or ""),
        )
        for item in report.changed_files
    ]
    return [
        "## Changed files",
        "",
        *table(("Path", "Change", "Base path"), rows),
        "",
    ]


def _changed_symbols(symbols: Sequence[ChangedSymbol]) -> list[str]:
    if not symbols:
        return []
    rows = [
        (
            escape_cell(item.qualified_name),
            escape_cell(item.symbol_kind.value),
            escape_cell(item.change_kind.value),
            escape_cell(item.file_path),
            escape_cell(_range(item)),
        )
        for item in symbols
    ]
    return [
        "## Changed symbols",
        "",
        *table(("Symbol", "Kind", "Change", "File", "Lines"), rows),
        "",
    ]


def _findings(
    findings: Sequence[Finding], evidence: Sequence[ChangeEvidenceItem]
) -> list[str]:
    if not findings:
        return ["## Findings", "", "No findings.", ""]

    by_id = {item.evidence_id: item for item in evidence}
    lines = ["## Findings", ""]
    for severity in _SEVERITY_ORDER:
        matching = [item for item in findings if item.severity is severity]
        if not matching:
            continue
        lines += [f"### {severity.value.title()}", ""]
        for finding in matching:
            lines.append(
                f"- **{escape_inline(finding.title)}**"
                f" (`{escape_inline(finding.code)}`)"
            )
            lines.append(f"  - {escape_inline(finding.description)}")
            lines.append(
                f"  - Derivation: `{escape_inline(finding.derivation.value)}`,"
                f" confidence {finding.confidence:.2f}"
            )
            for evidence_id in finding.evidence_ids:
                item = by_id.get(evidence_id)
                if item is not None:
                    lines.append(f"  - Evidence: {_location(item)}")
            if finding.remediation:
                lines.append(f"  - Remediation: {escape_inline(finding.remediation)}")
            for limitation in finding.limitations:
                lines.append(f"  - Limitation: {escape_inline(limitation)}")
        lines.append("")
    return lines


def _impact(report: ChangeAnalysisReport) -> list[str]:
    if not report.impact_edges:
        return []
    rows = [
        (
            escape_cell(edge.source),
            escape_cell(edge.kind.value),
            escape_cell(edge.target),
            escape_cell(edge.derivation.value),
        )
        for edge in report.impact_edges
    ]
    return [
        "## Impact",
        "",
        *table(("Changed", "Relation", "Reaches", "Derivation"), rows),
        "",
    ]


def _test_gaps(report: ChangeAnalysisReport) -> list[str]:
    """Every gap, with the reason it is still a gap.

    The disclaimer is not a footnote to be trimmed. A missing `TESTS` edge does
    not prove absence of coverage, and only executing the suite could cross that
    line — which CodeAtlas does not do.
    """
    if not report.test_gaps:
        return []

    by_name = {item.qualified_name: item for item in report.test_gap_reasons}
    by_id = {item.evidence_id: item for item in report.evidence}

    lines = [
        "## Possible test gaps",
        "",
        "A missing `TESTS` edge does not prove absence of coverage. CodeAtlas "
        "does not execute tests and cannot claim any symbol is untested.",
        "",
    ]
    for name in report.test_gaps:
        lines.append(f"- `{escape_inline(name)}`")
        reason = by_name.get(name)
        if reason is None:
            # A gap with no recorded reason is still a gap. Reporting the name
            # alone is honest; inventing a reason would not be.
            continue
        lines.append(f"  - Reason: `{escape_inline(reason.reason.value)}`")
        lines.append(f"  - {escape_inline(reason.explanation)}")
        for evidence_id in reason.evidence_ids:
            item = by_id.get(evidence_id)
            if item is not None:
                lines.append(f"  - Evidence: {_location(item)}")
    lines.append("")
    return lines


def _evidence(evidence: Sequence[ChangeEvidenceItem]) -> list[str]:
    if not evidence:
        return []
    rows = [
        (
            escape_cell(item.evidence_id),
            escape_cell(item.side.value),
            escape_cell(item.file_path),
            escape_cell(f"{item.start_line}-{item.end_line}"),
            escape_cell(item.symbol or ""),
        )
        for item in evidence
    ]
    return [
        "## Evidence",
        "",
        *table(("ID", "Side", "File", "Lines", "Symbol"), rows),
        "",
    ]


def _bullets(heading: str, values: Sequence[str]) -> list[str]:
    if not values:
        return []
    return [f"## {heading}", "", *(f"- {escape_inline(item)}" for item in values), ""]


def _range(symbol: ChangedSymbol) -> str:
    if symbol.target_start_line is not None and symbol.target_end_line is not None:
        return f"{symbol.target_start_line}-{symbol.target_end_line}"
    if symbol.base_start_line is not None and symbol.base_end_line is not None:
        return f"{symbol.base_start_line}-{symbol.base_end_line} (base)"
    return ""


def _location(item: ChangeEvidenceItem) -> str:
    return (
        f"`{escape_inline(item.file_path)}`"
        f" lines {item.start_line}-{item.end_line} ({escape_inline(item.side.value)})"
    )
