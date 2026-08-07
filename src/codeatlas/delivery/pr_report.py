"""A rendering of one change analysis shaped for a pull request.

:func:`codeatlas.delivery.render_markdown` is the audit format: complete, flat,
every evidence row present. That is right for an archive and wrong for a review.
A reviewer wants a verdict, the risks in order, and the option to expand the
rest.

This renderer adds no facts. It reorders and folds what the report already
carries, and it never drops a finding or a test gap.
"""

from __future__ import annotations

from typing import Final

from codeatlas.contracts import (
    ChangeAnalysisReport,
    ChangeEvidenceItem,
    Finding,
    GapReason,
    Severity,
)
from codeatlas.delivery.markdown_text import escape_inline

_SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)


def render_pr_markdown(report: ChangeAnalysisReport) -> str:
    """Render one persisted analysis for pasting into a pull request."""
    lines = _headline(report) + _findings(report) + _gaps(report)
    return "\n".join(lines).rstrip() + "\n"


def _headline(report: ChangeAnalysisReport) -> list[str]:
    symbols = len(report.changed_symbols)
    files = len(report.changed_files)
    findings = len(report.findings)
    gaps = len(report.test_gaps)
    risk = escape_inline(report.overall_risk.value.upper())
    return [
        f"## CodeAtlas preflight — **{risk}** risk",
        "",
        f"{symbols} {_plural(symbols, 'symbol')} changed across "
        f"{files} {_plural(files, 'file')} · "
        f"{findings} {_plural(findings, 'finding')} · "
        f"{gaps} possible test {_plural(gaps, 'gap')}",
        "",
        f"Base `{escape_inline(report.base.ref)}` "
        f"({escape_inline(report.base.commit or 'no commit')}, "
        f"{escape_inline(report.base.freshness.value)}) → "
        f"target `{escape_inline(report.target.ref)}` "
        f"({escape_inline(report.target.commit or 'no commit')}, "
        f"{escape_inline(report.target.freshness.value)})",
        "",
    ]


def _findings(report: ChangeAnalysisReport) -> list[str]:
    if not report.findings:
        return [
            "### Findings",
            "",
            "No findings. That is not a claim that the change is safe — only "
            "that no rule matched it.",
            "",
        ]

    by_id = {item.evidence_id: item for item in report.evidence}
    lines = ["### Findings", ""]
    for severity in _SEVERITY_ORDER:
        for finding in [item for item in report.findings if item.severity is severity]:
            lines += _one_finding(finding, by_id)
    return lines


def _one_finding(
    finding: Finding, by_id: dict[str, ChangeEvidenceItem]
) -> list[str]:
    lines = [
        f"**{escape_inline(finding.severity.value.upper())} — "
        f"{escape_inline(finding.title)}** "
        f"(`{escape_inline(finding.code)}`)",
        "",
        escape_inline(finding.description),
        "",
        # Derivation and confidence are separate facts: a high-confidence
        # heuristic is still a heuristic, and a score never promotes it.
        f"`{escape_inline(finding.derivation.value)}` · "
        f"confidence {finding.confidence:.2f}",
        "",
    ]
    for evidence_id in finding.evidence_ids:
        item = by_id.get(evidence_id)
        if item is not None:
            lines += [_evidence_line(item), ""]
    if finding.remediation:
        lines += [f"Remediation: {escape_inline(finding.remediation)}", ""]
    for limitation in finding.limitations:
        lines += [f"Limitation: {escape_inline(limitation)}", ""]
    return lines


def _gaps(report: ChangeAnalysisReport) -> list[str]:
    """Possible test gaps, each with the reason it is still a gap.

    The disclaimer is mandatory. A missing `TESTS` edge does not prove absence
    of coverage, and only executing the suite could cross that line — which
    CodeAtlas does not do. The heading says "possible" for the same reason.
    """
    if not report.test_gaps:
        return []

    by_name = {item.qualified_name: item for item in report.test_gap_reasons}
    lines = [
        "### Possible test gaps",
        "",
        "A missing `TESTS` edge does not prove absence of coverage. CodeAtlas "
        "does not execute tests and cannot claim any symbol is untested.",
        "",
    ]
    lines += [_one_gap(name, by_name.get(name)) for name in report.test_gaps]
    lines.append("")
    return lines


def _one_gap(name: str, reason: GapReason | None) -> str:
    if reason is None:
        # A gap with no recorded reason is still a gap. Inventing one would be
        # the fabrication this product exists to refuse.
        return f"- `{escape_inline(name)}`"
    return (
        f"- `{escape_inline(name)}` — {escape_inline(reason.explanation)} "
        f"(`{escape_inline(reason.reason.value)}`)"
    )


def _evidence_line(item: ChangeEvidenceItem) -> str:
    """One citation as text.

    Never a forge URL: a permalink needs a host, owner, repository and commit
    that CodeAtlas does not have and would have to guess, and a wrong permalink
    is a citation pointing at the wrong code.
    """
    return (
        f"`{escape_inline(item.file_path)}:"
        f"{item.start_line}-{item.end_line}` "
        f"({escape_inline(item.side.value)}) · "
        f"`{escape_inline(item.derivation.value)}` · "
        f"confidence {item.confidence:.2f}"
    )


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"
