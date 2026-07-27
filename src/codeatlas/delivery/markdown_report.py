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

import re
from collections.abc import Iterable, Sequence
from typing import Final

from codeatlas.contracts import (
    ChangeAnalysisReport,
    ChangedSymbol,
    ChangeEvidenceItem,
    Finding,
    Severity,
)

_SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)

# Control characters would let repository content move the cursor or blank a
# line in a terminal that renders the Markdown.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_CELL_LENGTH: Final[int] = 160


def render_markdown(report: ChangeAnalysisReport) -> str:
    """Render one persisted analysis as Markdown."""
    lines: list[str] = [
        "# Change analysis",
        "",
        f"- **Analysis**: `{_inline(report.analysis_id)}`",
        f"- **Repository**: `{_inline(report.repository_id)}`",
        f"- **Kind**: {_inline(report.kind.value)}",
        f"- **Overall risk**: **{_inline(report.overall_risk.value)}**",
        f"- **Base**: `{_inline(report.base.ref)}`"
        f" ({_inline(report.base.commit or 'no commit')}, "
        f"{_inline(report.base.freshness.value)})",
        f"- **Target**: `{_inline(report.target.ref)}`"
        f" ({_inline(report.target.commit or 'no commit')}, "
        f"{_inline(report.target.freshness.value)})",
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
        (_cell(item.path), _cell(item.change_kind.value), _cell(item.base_path or ""))
        for item in report.changed_files
    ]
    return [
        "## Changed files",
        "",
        *_table(("Path", "Change", "Base path"), rows),
        "",
    ]


def _changed_symbols(symbols: Sequence[ChangedSymbol]) -> list[str]:
    if not symbols:
        return []
    rows = [
        (
            _cell(item.qualified_name),
            _cell(item.symbol_kind.value),
            _cell(item.change_kind.value),
            _cell(item.file_path),
            _cell(_range(item)),
        )
        for item in symbols
    ]
    return [
        "## Changed symbols",
        "",
        *_table(("Symbol", "Kind", "Change", "File", "Lines"), rows),
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
            lines.append(f"- **{_inline(finding.title)}** (`{_inline(finding.code)}`)")
            lines.append(f"  - {_inline(finding.description)}")
            lines.append(
                f"  - Derivation: `{_inline(finding.derivation.value)}`,"
                f" confidence {finding.confidence:.2f}"
            )
            for evidence_id in finding.evidence_ids:
                item = by_id.get(evidence_id)
                if item is not None:
                    lines.append(f"  - Evidence: {_location(item)}")
            if finding.remediation:
                lines.append(f"  - Remediation: {_inline(finding.remediation)}")
            for limitation in finding.limitations:
                lines.append(f"  - Limitation: {_inline(limitation)}")
        lines.append("")
    return lines


def _impact(report: ChangeAnalysisReport) -> list[str]:
    if not report.impact_edges:
        return []
    rows = [
        (
            _cell(edge.source),
            _cell(edge.kind.value),
            _cell(edge.target),
            _cell(edge.derivation.value),
        )
        for edge in report.impact_edges
    ]
    return [
        "## Impact",
        "",
        *_table(("Changed", "Relation", "Reaches", "Derivation"), rows),
        "",
    ]


def _test_gaps(report: ChangeAnalysisReport) -> list[str]:
    if not report.test_gaps:
        return []
    return [
        "## Possible test gaps",
        "",
        "A missing `TESTS` edge does not prove absence of coverage. CodeAtlas "
        "does not execute tests and cannot claim any symbol is untested.",
        "",
        *(f"- `{_inline(name)}`" for name in report.test_gaps),
        "",
    ]


def _evidence(evidence: Sequence[ChangeEvidenceItem]) -> list[str]:
    if not evidence:
        return []
    rows = [
        (
            _cell(item.evidence_id),
            _cell(item.side.value),
            _cell(item.file_path),
            _cell(f"{item.start_line}-{item.end_line}"),
            _cell(item.symbol or ""),
        )
        for item in evidence
    ]
    return [
        "## Evidence",
        "",
        *_table(("ID", "Side", "File", "Lines", "Symbol"), rows),
        "",
    ]


def _bullets(heading: str, values: Sequence[str]) -> list[str]:
    if not values:
        return []
    return [f"## {heading}", "", *(f"- {_inline(item)}" for item in values), ""]


def _table(
    headers: Sequence[str], rows: Iterable[Sequence[str]]
) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _range(symbol: ChangedSymbol) -> str:
    if symbol.target_start_line is not None and symbol.target_end_line is not None:
        return f"{symbol.target_start_line}-{symbol.target_end_line}"
    if symbol.base_start_line is not None and symbol.base_end_line is not None:
        return f"{symbol.base_start_line}-{symbol.base_end_line} (base)"
    return ""


def _location(item: ChangeEvidenceItem) -> str:
    return (
        f"`{_inline(item.file_path)}`"
        f" lines {item.start_line}-{item.end_line} ({_inline(item.side.value)})"
    )


def _inline(value: str) -> str:
    """Escape a value for inline Markdown.

    Backticks are the dangerous ones: repository text containing one can close a
    code span and let the rest render as markup. Pipes are escaped too so a value
    interpolated near a table cannot introduce a column.
    """
    text = _CONTROL.sub("", value)
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _cell(value: str) -> str:
    """Escape a value for a table cell and bound its length.

    A cell is truncated rather than wrapped: an unbounded value from repository
    content would push a table past any width and make the whole report
    unreadable.
    """
    text = _inline(value)
    if len(text) > MAX_CELL_LENGTH:
        return text[: MAX_CELL_LENGTH - 1] + "…"
    return text
