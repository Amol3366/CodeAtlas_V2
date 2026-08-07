# CLI Impact UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `codeatlas impact` answer "should I worry, and about what?" — a terminal-shaped verdict by default, `--fail-on` for CI exit codes, `--since` for branch ranges — and fix a live defect where `--format pr` is advertised but rejected.

**Architecture:** A fifth renderer, `render_text`, shaped for a terminal rather than a document, becomes `impact`'s default. Two flags are added to the same command. The severity ordering — currently duplicated across two renderers — moves to `contracts.py` where `--fail-on` can also reach it. `--since` needs one new method on the Git adapter, because a two-dot diff against a moved trunk analyses the wrong range.

**Tech Stack:** Python 3.12, Typer, Pydantic 2, Git CLI via argument-array subprocess. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-08-cli-impact-ux-design.md`

## Global Constraints

- `contract_version` stays `"1.1"`; `SCHEMA_VERSION` stays `14`; **no migration**.
- Python pinned `>=3.12,<3.13`. Add **no** dependency.
- Type hints throughout. MyPy must pass (`uv run mypy --no-incremental src`).
- Comments explain *why*, not *what*.
- Do **not** delete, skip, or weaken an existing test.
- **Never claim a symbol is tested or untested.**
- All repository-derived text is untrusted. The text renderer writes to a terminal, so control characters must be stripped.
- **`render_markdown`, `render_pr_markdown`, and `render_sarif` must not change.** Verified by an empty diff in Task 7.
- **No colour and no `isatty` branching** — output is identical piped, redirected, or in CI.
- Git is invoked through the existing argument-array subprocess path, never a shell.
- Use `uv run` for all Python commands.

## Reference: what exists today

- `src/codeatlas/cli/main.py` — exit codes at `:77-82`; `_fail` at `:170`; `impact` at `:1228`; `analysis` at `:1289`; `_print_report` at `:1312`.
- **Both** `impact` (`:1249`) and `analysis` (`:1297`) carry `if report_format not in {"json", "markdown", "sarif"}:` — the defect.
- `_print_report` already has a `pr` branch; only the guards are stale.
- `_SEVERITY_ORDER` is duplicated: `delivery/markdown_report.py:29` and `delivery/pr_report.py:26`.
- `delivery/markdown_text.py` — `escape_inline`, `escape_cell`, `table`, `MAX_CELL_LENGTH`.
- `repositories/git_diff.py` — `resolve_ref` at `:64` is the model for `merge_base`; `_validate_ref` at `:305`; `_run` at `:415` returns `(stdout, failure_code)`.
- `GitRefUnresolvableError` (code `GIT_REF_UNRESOLVABLE`) in `domain/errors.py`.
- CLI tests live in `tests/contract/` — `test_maintenance_cli.py`, `test_settings_cli.py`.
- `Severity` values: `critical`, `high`, `medium`, `low`, `info`.

---

### Task 1: Fix `--format pr`, and correct the record

`codeatlas impact --format pr` exits `INVALID_REQUEST` while its own `--help` advertises `pr`. Two allow-lists never learned the value. The one-line fix is trivial; the test that stops it recurring is the deliverable.

**Files:**
- Modify: `src/codeatlas/cli/main.py:1249` and `:1297`
- Create: `tests/contract/test_impact_cli.py`
- Modify: `documentation/memory.md`, `docs/plans/PLAN.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `ADVERTISED_FORMATS: frozenset[str] = frozenset({"json", "markdown", "pr", "sarif"})` in `src/codeatlas/cli/main.py`, used by both guards. Later tasks add `"text"` to it.

- [ ] **Step 1: Write the failing test**

Read `tests/contract/test_maintenance_cli.py` first for how it builds a repository and invokes the Typer app, and follow that exactly.

```python
"""The `impact` and `analysis` commands."""

from __future__ import annotations

import pytest

from codeatlas.cli.main import ADVERTISED_FORMATS


@pytest.mark.parametrize("report_format", sorted(ADVERTISED_FORMATS))
def test_every_advertised_format_is_accepted_by_impact(
    prepared, report_format: str
) -> None:
    """Help that enumerates formats is a promise about them.

    This is the test whose absence let `--format pr` ship advertised but
    rejected: the guard and the help string were separate lists, and only one
    was updated.
    """
    result = invoke_cli(
        ["impact", prepared.repository_id, "--format", report_format,
         "--db", str(prepared.database)]
    )

    assert result.exit_code in (0, 4), result.output
    assert "INVALID_REQUEST" not in result.output


@pytest.mark.parametrize("report_format", sorted(ADVERTISED_FORMATS))
def test_every_advertised_format_is_accepted_by_analysis(
    prepared, report_format: str
) -> None:
    analysis_id = run_one_analysis(prepared)

    result = invoke_cli(
        ["analysis", analysis_id, "--format", report_format,
         "--db", str(prepared.database)]
    )

    assert result.exit_code == 0, result.output


def test_an_unknown_format_is_refused(prepared) -> None:
    # A typo must fail loudly, not quietly select a default.
    result = invoke_cli(
        ["impact", prepared.repository_id, "--format", "prr",
         "--db", str(prepared.database)]
    )

    assert result.exit_code == 2
    assert "INVALID_REQUEST" in result.output
```

`invoke_cli`, `prepared`, and `run_one_analysis` follow the conventions in `tests/contract/test_maintenance_cli.py`. `exit_code in (0, 4)` because `impact` exits `4` when an analysis finds nothing — that is existing documented behaviour and not what this test is about.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contract/test_impact_cli.py -v`
Expected: FAIL — `ADVERTISED_FORMATS` does not exist; once defined, the `pr` parameter case fails on `INVALID_REQUEST`.

- [ ] **Step 3: Implement**

In `src/codeatlas/cli/main.py`, beside the exit codes:

```python
# One list, used by the guards and named in the help text. Two lists is how
# `--format pr` shipped advertised but rejected.
ADVERTISED_FORMATS: Final[frozenset[str]] = frozenset(
    {"json", "markdown", "pr", "sarif"}
)
```

Replace **both** guards (`:1249` and `:1297`) with:

```python
    if report_format not in ADVERTISED_FORMATS:
        typer.echo(
            "INVALID_REQUEST: --format must be one of "
            f"{', '.join(sorted(ADVERTISED_FORMATS))}.",
            err=True,
        )
        raise typer.Exit(EXIT_INVALID_INPUT)
```

Add `Final` to the `typing` import if absent.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/contract/test_impact_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Correct the record**

Both `documentation/memory.md` and the `2026-08-08T00:30:00Z` handoff in `docs/plans/PLAN.md` state that `_print_report` silently prints JSON for an unknown `--format`. **That is false** — both commands validate first, so its `else` branch is unreachable from either.

Correct both entries in place. Do not delete them: state what was recorded, that it was wrong, and what the real defect was (`--format pr` advertised but rejected, because the PR-export slice's cross-adapter test covered REST and MCP and never invoked the CLI).

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/cli/main.py tests/contract/test_impact_cli.py documentation docs
git commit -m "fix: accept --format pr, which help already advertised"
```

---

### Task 2: One severity ordering

`_SEVERITY_ORDER` exists twice — `delivery/markdown_report.py:29` and `delivery/pr_report.py:26`. A third renderer arrives in Task 3, and `--fail-on` in Task 5 needs it from outside `delivery` entirely.

**Files:**
- Modify: `src/codeatlas/contracts.py` (after the `Severity` enum)
- Modify: `src/codeatlas/delivery/markdown_report.py:29`
- Modify: `src/codeatlas/delivery/pr_report.py:26`
- Modify: `tests/unit/test_markdown_report.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SEVERITY_ORDER: Final[tuple[Severity, ...]]` in `codeatlas.contracts`, ordered critical → info.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_markdown_report.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_markdown_report.py -k severity -v`
Expected: FAIL — `ImportError` on `SEVERITY_ORDER`.

- [ ] **Step 3: Implement**

In `src/codeatlas/contracts.py`, immediately after the `Severity` enum:

```python
SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)
"""Severity from worst to least, most-severe first.

Here rather than in a renderer because the ordering is a property of the
severity vocabulary itself, and `--fail-on` needs it from outside `delivery`.
"""
```

Add `Final` to the `typing` import if absent.

Then in **both** `markdown_report.py` and `pr_report.py`: delete the local `_SEVERITY_ORDER`, import `SEVERITY_ORDER` from `codeatlas.contracts`, and replace each use. Behaviour is unchanged.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit tests/contract -q`
Expected: PASS. Both renderers' existing ordering tests are the proof this was behaviour-preserving.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/contracts.py src/codeatlas/delivery tests/unit/test_markdown_report.py
git commit -m "refactor: one severity ordering, in contracts"
```

---

### Task 3: `render_text`

**Files:**
- Create: `src/codeatlas/delivery/text_report.py`
- Create: `tests/unit/test_text_report.py`
- Modify: `src/codeatlas/delivery/__init__.py`
- Modify: `src/codeatlas/cli/main.py` (`ADVERTISED_FORMATS`, `_print_report`, both help strings)

**Interfaces:**
- Consumes: `SEVERITY_ORDER` from Task 2; `escape_inline` is **not** used (see Step 3).
- Produces: `render_text(report: ChangeAnalysisReport) -> str`, exported from `codeatlas.delivery`. `ADVERTISED_FORMATS` gains `"text"`.

- [ ] **Step 1: Write the failing test**

Copy the `_state` / `_report` / `_finding` / `_evidence` helpers from `tests/unit/test_pr_report.py` into this module — a test module importing fixtures from another couples two suites that should fail independently. Remember `Finding.evidence_ids` needs `min_length=1` and every id must exist in `report.evidence`.

```python
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
```

Add an `_edge(...)` helper as in `test_pr_report.py`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_text_report.py -v`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement**

```python
"""A rendering of one change analysis for a terminal.

The Markdown and PR renderings are documents. This one is a verdict: a reader
at a prompt wants to know whether to worry and about what, not to scroll a
table of every evidence row.

No colour is used, at all. `documentation/design.md` requires that colour is
never the only signal, and the simplest way to satisfy that here is not to
depend on it — which also keeps the output identical when piped, redirected, or
captured by CI, with no `isatty` branching to get wrong.
"""

from __future__ import annotations

import re
from typing import Final

from codeatlas.contracts import (
    SEVERITY_ORDER,
    ChangeAnalysisReport,
    ChangeEvidenceItem,
    Derivation,
    Finding,
)

# Repository text reaching a terminal could move the cursor or blank a line.
# The Markdown renderers strip the same range; a terminal is where it matters
# most.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INDENT: Final[str] = "  "


def render_text(report: ChangeAnalysisReport) -> str:
    """Render one analysis as plain text for a terminal."""
    lines = _verdict(report) + _findings(report) + _gaps(report) + _impact(report)
    return "\n".join(lines).rstrip() + "\n"


def _clean(value: str) -> str:
    return _CONTROL.sub("", value)


def _verdict(report: ChangeAnalysisReport) -> list[str]:
    symbols = len(report.changed_symbols)
    files = len(report.changed_files)
    findings = len(report.findings)
    gaps = len(report.test_gaps)
    return [
        f"{_clean(report.overall_risk.value.upper())} risk · "
        f"{symbols} {_plural(symbols, 'symbol')} across "
        f"{files} {_plural(files, 'file')} · "
        f"{findings} {_plural(findings, 'finding')} · "
        f"{gaps} possible test {_plural(gaps, 'gap')}",
        f"base {_clean(report.base.ref)} "
        f"({_clean(report.base.commit or 'no commit')}, "
        f"{_clean(report.base.freshness.value)}) → "
        f"target {_clean(report.target.ref)} "
        f"({_clean(report.target.freshness.value)})",
        "",
    ]


def _findings(report: ChangeAnalysisReport) -> list[str]:
    if not report.findings:
        return [
            "FINDINGS",
            f"{_INDENT}None. That is not a claim that the change is safe — only",
            f"{_INDENT}that no rule matched it.",
            "",
        ]

    by_id = {item.evidence_id: item for item in report.evidence}
    lines = ["FINDINGS"]
    for severity in SEVERITY_ORDER:
        for finding in [f for f in report.findings if f.severity is severity]:
            lines += _one_finding(finding, by_id)
    return lines


def _one_finding(
    finding: Finding, by_id: dict[str, ChangeEvidenceItem]
) -> list[str]:
    label = _clean(finding.severity.value.upper()).ljust(8)
    lines = [
        f"{_INDENT}{label}{_clean(finding.title)}  {_clean(finding.code)}",
        f"{_INDENT}        {_clean(finding.description)}",
        f"{_INDENT}        {_clean(finding.derivation.value)} · "
        f"{finding.confidence:.2f}",
    ]
    for evidence_id in finding.evidence_ids:
        item = by_id.get(evidence_id)
        if item is not None:
            lines.append(
                f"{_INDENT}        {_clean(item.file_path)}:"
                f"{item.start_line}-{item.end_line} "
                f"({_clean(item.side.value)})"
            )
    lines.append("")
    return lines


def _gaps(report: ChangeAnalysisReport) -> list[str]:
    """Possible test gaps and why each is still one.

    The disclaimer is mandatory. A missing `TESTS` edge does not prove absence
    of coverage, and only executing the suite could cross that line — which
    CodeAtlas does not do.
    """
    if not report.test_gaps:
        return []

    by_name = {item.qualified_name: item for item in report.test_gap_reasons}
    lines = [
        "POSSIBLE TEST GAPS",
        f"{_INDENT}A missing TESTS edge does not prove absence of coverage.",
        f"{_INDENT}CodeAtlas does not execute tests.",
        "",
    ]
    for name in report.test_gaps:
        reason = by_name.get(name)
        if reason is None:
            # A gap with no recorded reason is still a gap. Inventing one would
            # be the fabrication this product exists to refuse.
            lines.append(f"{_INDENT}{_clean(name)}")
        else:
            lines.append(
                f"{_INDENT}{_clean(name)}  {_clean(reason.explanation)}  "
                f"{_clean(reason.reason.value)}"
            )
    lines.append("")
    return lines


def _impact(report: ChangeAnalysisReport) -> list[str]:
    """A count, not a list.

    The full edge table is what `--format markdown` is for. The weak count is
    called out because a `low_confidence_heuristic` edge is a candidate rather
    than coverage (ADR-0016), and a summary that hid the distinction would undo
    it.
    """
    if not report.impact_edges:
        return []
    weak = sum(
        1
        for edge in report.impact_edges
        if edge.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC
    )
    total = len(report.impact_edges)
    line = f"IMPACT{_INDENT}{total} {_plural(total, 'edge')}"
    if weak:
        line += f", {weak} low_confidence_heuristic"
    return [line, ""]


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"
```

- [ ] **Step 4: Wire it as a format**

Export from `src/codeatlas/delivery/__init__.py`:

```python
from codeatlas.delivery.text_report import render_text

__all__ = ["render_markdown", "render_pr_markdown", "render_sarif", "render_text"]
```

In `src/codeatlas/cli/main.py`: add `"text"` to `ADVERTISED_FORMATS`, add a `text` branch to `_print_report`, and update **both** `--format` help strings to `"json, markdown, pr, sarif, or text."`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_text_report.py tests/contract/test_impact_cli.py -v`
Expected: PASS. Task 1's parameterised test now covers `text` automatically — that is the point of deriving it from `ADVERTISED_FORMATS`.

- [ ] **Step 6: Mutation-check the disclaimer**

Delete the two disclaimer lines from `_gaps`. Confirm `test_the_gap_disclaimer_is_present_whenever_a_gap_is` FAILS. Restore and confirm it passes. Record both halves in your report.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/delivery src/codeatlas/cli/main.py tests/unit/test_text_report.py
git commit -m "feat: a terminal rendering of a change analysis"
```

---

### Task 4: `text` becomes `impact`'s default

**Files:**
- Modify: `src/codeatlas/cli/main.py` (`impact`'s `report_format` default)
- Modify: `tests/contract/test_impact_cli.py`

**Interfaces:**
- Consumes: Task 3's `render_text`.
- Produces: no new name. `impact` defaults to `text`; `analysis` still defaults to `markdown`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_bare_impact_prints_the_terminal_rendering(prepared) -> None:
    result = invoke_cli(["impact", prepared.repository_id, "--db", str(prepared.database)])

    assert "risk ·" in result.output
    assert "# Change analysis" not in result.output


def test_markdown_is_still_available_and_unchanged(prepared) -> None:
    result = invoke_cli(
        ["impact", prepared.repository_id, "--format", "markdown",
         "--db", str(prepared.database)]
    )

    assert "# Change analysis" in result.output


def test_analysis_still_defaults_to_markdown(prepared) -> None:
    # `analysis` prints a stored record, which is the archival case.
    analysis_id = run_one_analysis(prepared)

    result = invoke_cli(["analysis", analysis_id, "--db", str(prepared.database)])

    assert "# Change analysis" in result.output
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contract/test_impact_cli.py -v`
Expected: the bare-impact test FAILS — it still prints Markdown.

- [ ] **Step 3: Implement**

In `impact`'s signature, change the default:

```python
    report_format: Annotated[
        str,
        typer.Option("--format", help="json, markdown, pr, sarif, or text."),
    ] = "text",
```

Leave `analysis`'s default at `"markdown"`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/contract -q`
Expected: PASS. If another test asserted Markdown from a bare `impact`, it was asserting the old default — update it deliberately and say so in your report.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/cli/main.py tests/contract/test_impact_cli.py
git commit -m "feat: impact prints a verdict by default"
```

---

### Task 5: `--fail-on`

**Files:**
- Modify: `src/codeatlas/cli/main.py` (exit codes, `impact`)
- Modify: `tests/contract/test_impact_cli.py`

**Interfaces:**
- Consumes: `SEVERITY_ORDER` from Task 2.
- Produces: `EXIT_RISK_THRESHOLD = 7`; `impact --fail-on <severity>`.

- [ ] **Step 1: Write the failing test**

```python
def test_fail_on_exits_seven_when_a_finding_meets_the_threshold(prepared) -> None:
    result = invoke_cli(
        ["impact", prepared.repository_id, "--fail-on", "low",
         "--db", str(prepared.database)]
    )

    assert result.exit_code == 7


def test_fail_on_exits_zero_when_nothing_meets_the_threshold(prepared) -> None:
    result = invoke_cli(
        ["impact", prepared.repository_id, "--fail-on", "critical",
         "--db", str(prepared.database)]
    )

    assert result.exit_code == 0


def test_fail_on_still_prints_the_report(prepared) -> None:
    # A CI log showing only an exit code is not diagnosable.
    result = invoke_cli(
        ["impact", prepared.repository_id, "--fail-on", "low",
         "--db", str(prepared.database)]
    )

    assert "risk ·" in result.output


def test_an_unknown_fail_on_value_is_refused(prepared) -> None:
    # A typo in a CI config must fail loudly, not silently disable the check.
    result = invoke_cli(
        ["impact", prepared.repository_id, "--fail-on", "sever",
         "--db", str(prepared.database)]
    )

    assert result.exit_code == 2
    assert "INVALID_REQUEST" in result.output


def test_without_fail_on_the_exit_codes_are_unchanged(prepared) -> None:
    # Exit 4 for no findings is documented existing behaviour and stays.
    result = invoke_cli(["impact", prepared.repository_id, "--db", str(prepared.database)])

    assert result.exit_code in (0, 4)
```

The fixture must produce at least one finding for the `low` cases. Check what `prepared` yields; if it produces none, edit the fixture tree so it does, and say so in your report.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contract/test_impact_cli.py -k fail_on -v`
Expected: FAIL — `--fail-on` is not a recognised option.

- [ ] **Step 3: Implement**

Beside the other exit codes:

```python
EXIT_RISK_THRESHOLD = 7
"""A finding met the severity threshold a caller set with `--fail-on`.

Deliberately not `EXIT_POLICY_FAILURE`, which already means PATH_NOT_ALLOWED
and SCAN_LIMIT_EXCEEDED. A CI job must be able to tell "your change is risky"
from "you pointed me at the wrong directory".
"""
```

Add the option to `impact`:

```python
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            help="Exit 7 if a finding is at or above this severity.",
        ),
    ] = None,
```

Validate before running anything:

```python
    threshold: Severity | None = None
    if fail_on is not None:
        try:
            threshold = Severity(fail_on)
        except ValueError:
            typer.echo(
                "INVALID_REQUEST: --fail-on must be one of "
                f"{', '.join(item.value for item in SEVERITY_ORDER)}.",
                err=True,
            )
            raise typer.Exit(EXIT_INVALID_INPUT) from None
```

After `_print_report(report, report_format)`, before the existing `EXIT_PARTIAL` branch:

```python
        if threshold is not None:
            rank = SEVERITY_ORDER.index(threshold)
            # SEVERITY_ORDER is most-severe-first, so "at or above" is a lower
            # or equal index.
            if any(
                SEVERITY_ORDER.index(finding.severity) <= rank
                for finding in report.findings
            ):
                raise typer.Exit(EXIT_RISK_THRESHOLD)
            return
```

The `return` matters: with `--fail-on` and nothing meeting it, the command exits `0` rather than falling through to the existing `EXIT_PARTIAL` branch. That is the whole point of the flag — a caller who asked "is anything at or above X?" got the answer "no".

Import `Severity` and `SEVERITY_ORDER` from `codeatlas.contracts`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/contract/test_impact_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/cli/main.py tests/contract/test_impact_cli.py
git commit -m "feat: --fail-on for CI-style exit codes"
```

---

### Task 6: `merge_base` and `--since`

**Files:**
- Modify: `src/codeatlas/repositories/git_diff.py` (new method after `resolve_ref` at `:64`)
- Modify: `src/codeatlas/application/change_analysis.py` (new `analyze_since`)
- Modify: `src/codeatlas/cli/main.py` (`impact`)
- Create: `tests/integration/test_git_merge_base.py`
- Modify: `tests/contract/test_impact_cli.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `GitDiffAdapter.merge_base(self, root: Path, ref: str) -> str`;
  `ChangeAnalysisService.analyze_since(request: ChangeAnalysisRequest, since_ref: str) -> ChangeAnalysisReport`;
  `impact --since <ref>`.

- [ ] **Step 1: Write the failing integration test**

Follow the `_git` subprocess helper convention in `tests/integration/test_change_analysis_service.py:48-81`.

```python
def test_merge_base_is_where_the_branch_diverged(tmp_path: Path) -> None:
    """The case that makes this method necessary.

    A two-dot diff against a trunk that has moved reports the trunk's own new
    commits as changes to your branch. Only a merge-base gives "what I changed".
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    divergence = _rev_parse(root, "HEAD")

    _git(root, "checkout", "-b", "feature")
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "feature work")

    _git(root, "checkout", "main")
    (root / "c.py").write_text("c = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "trunk moved on")
    _git(root, "checkout", "feature")

    adapter = GitDiffAdapter()

    assert adapter.merge_base(root, "main") == divergence


def test_an_unresolvable_ref_raises(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch", "main")
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")

    with pytest.raises(GitRefUnresolvableError):
        GitDiffAdapter().merge_base(root, "no-such-branch")
```

Add `_rev_parse(root, ref)` returning the stripped stdout of `git rev-parse <ref>`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_git_merge_base.py -v`
Expected: FAIL — `merge_base` does not exist.

- [ ] **Step 3: Implement `merge_base`**

In `src/codeatlas/repositories/git_diff.py`, after `resolve_ref`:

```python
    def merge_base(self, root: Path, ref: str) -> str:
        """Return the commit where ``ref`` and ``HEAD`` diverged.

        `--since main` is not `--base main`. A two-dot diff against a trunk that
        has moved reports the trunk's own new commits as changes to the branch,
        inverted. Only the merge-base answers "what did I change".
        """
        self._validate_ref(ref)
        stdout, failure = self._run(root, "merge-base", ref, "HEAD")
        if failure is not None or stdout is None:
            raise GitRefUnresolvableError(
                f"No merge base between {ref!r} and HEAD.",
                details={"ref": ref},
            )
        resolved = stdout.strip()
        if len(resolved) != 40 or not all(
            character in "0123456789abcdef" for character in resolved
        ):
            raise GitRefUnresolvableError(
                f"The merge base for {ref!r} was unexpected output.",
                details={"ref": ref, "output": resolved},
            )
        return resolved
```

`_validate_ref` already rejects a ref containing `..`, a leading `-`, or a NUL, so a hostile value cannot reach the argument array as a flag.

- [ ] **Step 4: Write the failing CLI test**

```python
def test_since_and_commits_together_are_refused(prepared) -> None:
    # A silent precedence rule would analyse a range the user did not ask for.
    result = invoke_cli(
        ["impact", prepared.repository_id, "--since", "main",
         "--commits", "HEAD~1..HEAD", "--db", str(prepared.database)]
    )

    assert result.exit_code == 2
    assert "INVALID_REQUEST" in result.output


def test_since_analyses_from_the_merge_base(prepared) -> None:
    result = invoke_cli(
        ["impact", prepared.repository_id, "--since", "main",
         "--db", str(prepared.database)]
    )

    assert result.exit_code in (0, 4), result.output
    assert "INVALID_REQUEST" not in result.output
```

- [ ] **Step 5: Implement `--since`**

Add the option to `impact`:

```python
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Analyze from where this ref and HEAD diverged, to HEAD.",
        ),
    ] = None,
```

Before running, reject conflicts:

```python
    chosen = [name for name, value in (("--since", since), ("--commits", commits)) if value]
    if len(chosen) > 1 or (chosen and base != "HEAD"):
        typer.echo(
            "INVALID_REQUEST: --since, --commits, and --base are mutually "
            "exclusive.",
            err=True,
        )
        raise typer.Exit(EXIT_INVALID_INPUT)
```

- [ ] **Step 5a: Add the application method first**

**The CLI must not compute the merge base.** `documentation/rules.md` states that adapters are thin and repository logic never lives in one — and resolving a repository root, invoking Git, and turning the result into a commit range is repository logic. The service already holds both pieces privately (`self._diff`, `self._resolve`), and reaching into them from the CLI would both break the boundary and leave REST and MCP unable to offer the same capability.

Add to `ChangeAnalysisService` in `src/codeatlas/application/change_analysis.py`, beside `analyze_commit_range`:

```python
    def analyze_since(
        self, request: ChangeAnalysisRequest, since_ref: str
    ) -> ChangeAnalysisReport:
        """Analyze from where ``since_ref`` and HEAD diverged, to HEAD.

        Not the same as a base of ``since_ref``: a two-dot diff against a trunk
        that has moved reports the trunk's own new commits as changes to this
        branch, inverted. Only the merge base answers "what did I change".
        """
        root = self._resolve(request.repository_id)
        state = self._git.read_state(root)
        if not state.is_repository:
            raise ChangeAnalysisRequiresGitError(
                "A --since analysis needs a Git repository to find the merge "
                "base in."
            )
        base = self._diff.merge_base(root, since_ref)
        return self.analyze_commit_range(
            ChangeAnalysisRequest(
                repository_id=request.repository_id,
                base_ref=base,
                target_ref="HEAD",
                request_id=request.request_id,
            )
        )
```

Check the real attribute names for the diff adapter and the Git state reader by reading the class's `__init__` — the container constructs it with `diff=GitDiffAdapter()`, and `analyze_working_tree` uses `self._git.read_state(root)` and `self._resolve(...)`. Use whatever those attributes are actually called.

- [ ] **Step 5b: Wire the CLI to it**

Inside the existing `with _services(database)` / `try` block, add a branch beside the `commits` one:

```python
            elif since is not None:
                report = services.change_analysis.analyze_since(
                    ChangeAnalysisRequest(
                        repository_id=repository_id,
                        request_id=f"cli_{uuid.uuid4().hex}",
                    ),
                    since_ref=since,
                )
```

A `CodeAtlasError` from the service falls into the existing `except CodeAtlasError` block, so `GIT_REF_UNRESOLVABLE` and `CHANGE_ANALYSIS_REQUIRES_GIT` map to their existing exit codes with no new handling.

If `ChangeAnalysisRequest` requires `base_ref`, pass the field's own default rather than inventing one — `analyze_since` overrides it anyway.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/integration/test_git_merge_base.py tests/contract/test_impact_cli.py tests/integration/test_change_analysis_service.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/repositories/git_diff.py src/codeatlas/application/change_analysis.py src/codeatlas/cli/main.py tests
git commit -m "feat: --since analyses from the merge base"
```

---

### Task 7: Quality gate and documentation

**Files:**
- Modify: `docs/operations/change-analysis.md`, `documentation/memory.md`, `docs/plans/PLAN.md`

- [ ] **Step 1: Run the full quality gate**

```bash
uv run ruff check src tests scripts
uv run mypy --no-incremental src
uv run pytest -q
```

Record each command, its exit code, and its output. Fix failures; do not skip or weaken a test.

- [ ] **Step 2: Confirm the other renderers did not change**

```bash
git diff main...HEAD -- src/codeatlas/delivery/markdown_report.py src/codeatlas/delivery/pr_report.py src/codeatlas/delivery/sarif_report.py
```

Expected: only the `SEVERITY_ORDER` import change from Task 2 in the first two, and **nothing at all** in `sarif_report.py`. Any rendering change is a scope violation — stop and report it.

- [ ] **Step 3: Confirm the contract did not move**

```bash
git diff main...HEAD -- src/codeatlas/storage/sqlite/migrations
grep -n 'CONTRACT_VERSION: Literal' src/codeatlas/contracts.py
```

Expected: no migration change; `contract_version` still `"1.1"`.

- [ ] **Step 4: Document it**

`docs/operations/change-analysis.md` gains: the `text` format and that `impact` defaults to it; the full exit-code table including `7` and the existing `4`; `--fail-on` and `--since` with the merge-base explanation of why `--since main` differs from `--base main`.

- [ ] **Step 5: Update the living docs**

- `documentation/memory.md` — append to Completed. Record that `--format pr` shipped advertised-but-rejected because the previous slice's cross-adapter test never invoked the CLI, and that the guard is now derived from one `ADVERTISED_FORMATS` set that the parameterised test iterates.
- `docs/plans/PLAN.md` — **append** a handoff. Never rewrite an earlier one.

- [ ] **Step 6: Commit**

```bash
git add docs documentation
git commit -m "docs: document the text format, --fail-on, and --since"
```

---

## Notes for the implementer

**Verified contract facts** — checked against `src/codeatlas/contracts.py`:

- `ChangeAnalysisStatus.COMPLETED`, not `COMPLETE`.
- `created_at` is required and must be a timezone-aware UTC `datetime`.
- `Finding.evidence_ids` has `min_length=1`, and every id must exist in `report.evidence` (`validate_membership`).
- `changed_symbols` cannot be non-empty while `changed_files` is empty.
- `Severity` values are `critical`, `high`, `medium`, `low`, `info`.

**Test helper names are illustrative.** `invoke_cli`, `prepared`, `run_one_analysis`, `_git`, `_rev_parse`, `_report`, `_finding`, `_edge` describe what each must do. Read `tests/contract/test_maintenance_cli.py` and `tests/integration/test_change_analysis_service.py` and follow their conventions. The assertions are the contract.

**Line numbers drift.** Every `path:line` reference was accurate at `2db94cb`. If a line does not contain what this plan says, locate the construct by name.

**The four invariants that must not be compromised:**
1. Every advertised format is accepted, proven by a test derived from `ADVERTISED_FORMATS` (Task 1).
2. The gap disclaimer renders whenever any gap does (Task 3, mutation-checked).
3. A weak impact edge is never invisible — the summary names the `low_confidence_heuristic` count (Task 3).
4. Without `--fail-on`, exit codes are exactly as they are today (Task 5).
