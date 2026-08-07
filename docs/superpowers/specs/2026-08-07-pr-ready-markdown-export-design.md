# PR-ready Markdown export

Status: approved design, not yet implemented
Date: 2026-08-07
Authority: `AGENTS.md` is the contract. This spec is subordinate to it.
Related: ADR-0005 (change assurance), ADR-0016 (derivation-tiered test edges).

## 1. Why

`render_markdown` (`src/codeatlas/delivery/markdown_report.py`) is an audit
rendering: complete, flat, every evidence row present, ordered for the record
rather than for a reader. Its own docstring says so — each section is a view of
a field the report already carries, and nothing is trimmed.

That is the right shape for an archive and the wrong shape for a pull request.
A reviewer opening a diff wants a verdict, the risks in order, and the option to
expand the rest. Nobody pastes an evidence table into a PR comment.

### The defect this also closes

**Neither existing renderer shows test-gap reasons.** ADR-0016 gave every test
gap a structured `GapReason` explaining why it is a gap, backed by the near-miss
edges that justify it. `markdown_report.py` renders bare names; `sarif_report.py`
renders none.

So the work that most distinguishes CodeAtlas is currently visible only in the
web Preflight screen. Every CLI, REST, and MCP consumer sees a list of names with
no explanation — the same "second surface" pattern the ADR-0016 whole-branch
review flagged for `related_tests`.

Adding reasons to the audit renderer is therefore in scope here, independently of
the PR format. It is a defect in that renderer, not a feature of this one.

## 2. Scope

**In scope.** A new `render_pr_markdown`; extraction of the shared Markdown
escaping into its own module; test-gap reasons in the audit renderer; a `"pr"`
value on `ReportFormat` wired through REST, CLI, and MCP; dedicated unit tests
for the new renderer and the extracted escaping.

**Out of scope.** Posting to a forge, generating permalinks, or any Git-hosting
integration (Section 6.3). Changing SARIF (Section 4.2). Changing analysis
behaviour: every field rendered here already exists on `ChangeAnalysisReport`.

**Out of scope, permanently.** Any claim that a symbol is tested or untested.

## 3. File structure

```
src/codeatlas/delivery/
  markdown_text.py     escape_inline, escape_cell, table   (extracted)
  markdown_report.py   render_markdown       — audit, existing, gains reasons
  pr_report.py         render_pr_markdown    — new
  sarif_report.py      render_sarif          — unchanged
```

### 3.1 Why the escaping is extracted first

Everything reaching a renderer came out of a repository and is untrusted.
`markdown_report.py:228-257` already handles it: a backtick that would close a
code span, a pipe that would forge a table column, control characters that would
move a terminal cursor, and a cell length bound so one enormous value cannot push
a table past any width.

A second renderer needs identical handling. Copying it creates two places to get
that wrong, and only one of them will be reviewed when someone next changes it —
which is how a security-relevant helper drifts.

`_inline`, `_cell`, `_table`, and `_CONTROL` move to `markdown_text.py` as
`escape_inline`, `escape_cell`, `table`, and `MAX_CELL_LENGTH`, and both
renderers import them. `markdown_report.py`'s behaviour is unchanged by the move.

This is a prerequisite of the feature, not an unrelated refactor: shipping a
second renderer with copy-pasted escaping is the scope creep.

## 4. The audit renderer gains test-gap reasons

`_test_gaps` in `markdown_report.py` currently emits the disclaimer and a bullet
per name. It gains, per gap: the `GapReasonCode`, the human explanation, and an
evidence reference for each backing evidence id.

The existing disclaimer stays exactly as it is and stays mandatory. A gap with no
matching reason still renders its name — the name is a real finding of the
analysis even when no reason accompanied it, and dropping it would under-report.

### 4.1 Existing tests

The Markdown assertions in `tests/contract/test_change_cross_adapter.py` are
behavioural substring checks, not byte-for-byte comparisons, so this addition
does not invalidate them. There is no byte-exact baseline of change-analysis
Markdown anywhere. (`scripts/run_phase4_baseline.py --check` compares the
*evaluation* report, produced by a different `render_markdown` in
`src/codeatlas/evaluation/runner.py:391`. It is unaffected.)

### 4.2 SARIF deliberately does not change

SARIF is a findings format for scanners. A test gap is explicitly **not** a
finding: `_test_gaps` in `src/codeatlas/analysis/impact.py` is documented as
informational and states that it "must never become a finding".

Emitting gaps as SARIF results would assert precisely what ADR-0016 refuses — it
would turn "no qualifying test edge was found" into "here is a problem with your
code", and a scanner consuming it would treat it as one. SARIF keeps rendering
findings only.

## 5. The PR rendering

### 5.1 Order

Verdict, then the two things a reviewer must act on, then everything else folded:

1. **Headline** — overall risk as a word, in bold.
2. **One-line summary** — counts, plus base and target refs with freshness.
3. **Findings** — risk-ordered, expanded.
4. **Possible test gaps** — with reasons, expanded, disclaimer mandatory.
5. `<details>` **What changed** — changed symbols, then changed files that
   produced no symbol.
6. `<details>` **What it reaches** — impact edges, each with its derivation.
7. `<details>` **Evidence** — the full table.
8. **Warnings and limitations** — never collapsed.

Findings and gaps are expanded because they are the reason to read the report.
Warnings and limitations are not collapsed because they qualify everything above
them, and a qualification behind a disclosure triangle is a qualification most
readers never see.

### 5.2 Derivation survives collapsing

Impact edges keep their `derivation` inside the `<details>` block. A
fixture-mediated `TESTS` edge carries `low_confidence_heuristic`, so "a test you
should probably run" cannot read as "a test that covers this" — the distinction
ADR-0016 exists to create, in the surface most likely to be quoted into a
review.

### 5.3 The gap disclaimer is mandatory

Whenever any gap is rendered, the PR output carries the same meaning fixed in
`markdown_report.py:167`: a missing `TESTS` edge does not prove absence of
coverage, and CodeAtlas does not execute tests. It is never collapsed and never
abbreviated away by the budget in Section 7.

The heading is "Possible test gaps". Never "Untested".

## 6. What the PR format does not do

### 6.1 No permalinks

Evidence renders as `path:line` text. It never constructs a
`https://github.com/…/blob/…#L40-L52` URL.

"No GitHub/GitLab or CI integration" is an explicit non-goal in
`documentation/PRD.md`. A permalink needs a host, an owner, a repository name and
a commit — CodeAtlas has none of them and would have to guess, and a wrong
permalink is a citation pointing at the wrong code.

### 6.2 No posting

The renderer returns a string. Nothing in this slice writes to a forge, opens a
network connection, or reads a token. The user pastes it, or a script they own
posts it.

### 6.3 No repository-specific formatting

No emoji status icons keyed to a forge's rendering, no HTML beyond `<details>`
and `<summary>`, which render as plain text where unsupported rather than as
markup.

## 7. Bounding

`MAX_CHARACTERS: Final[int] = 60_000`, named as a conservative bound and not as
any platform's limit. CodeAtlas does not know what it is being pasted into, and a
constant named after one forge would be wrong the moment it is pasted elsewhere.

Collapsing is free and hides nothing, so it always happens. Truncation is a last
resort with three rules:

1. **Cut from the end**, in whole sections, never mid-row or mid-sentence.
2. **Findings and test gaps are never cut.** They are rendered first precisely so
   the budget is spent on supporting detail instead.
3. **A cut is always declared**, on a final line naming which sections were
   omitted and directing the reader to the `markdown` or `json` format for the
   complete report.

A report that quietly drops a critical finding is worse than one that does not
fit. Leaving the output unbounded is not an option either: the platform would
truncate it arbitrarily, mid-sentence, with no notice — the same silent drop,
relocated somewhere CodeAtlas does not control.

If the disclaimer and a declared-truncation line alone would exceed the budget,
the output is still produced: correctness of the notice outranks the bound.

## 8. Adapters

`ReportFormat` gains `"pr"`:

| Adapter | Surface |
| --- | --- |
| REST | `GET /v1/change-analysis/{id}/report?report_format=pr` → `text/markdown` |
| CLI | `codeatlas impact --format pr`, `codeatlas analysis --format pr` |
| MCP | the report tool's `format: "pr"` |

All three, because `documentation/PRD.md` claims "four ways in, one brain" and a
format present in one adapter but not the others contradicts it. MCP included:
an agent asked to draft a PR description is a plausible caller, and withholding
the format would force it to reimplement this rendering worse.

Additive. Existing values keep working, `contract_version` stays `1.1`,
`SCHEMA_VERSION` stays `14`, no migration.

### 8.1 The three places the format list is written down

Each enumerates the valid formats and each must be updated, or the surface will
disagree with itself:

- `ReportFormat = Literal["json", "markdown", "sarif"]`
  (`src/codeatlas/api/routers/change_analysis.py:22`).
- `AnalysisReportInput.report_format: Literal[...]`
  (`src/codeatlas/mcp/tools.py:110`) — an agent reads this schema to learn what
  it may ask for, so a missing value is not merely cosmetic.
- The CLI `--format` help text, written out as "json, markdown, or sarif" at
  `src/codeatlas/cli/main.py:1240` and again at `:1292`. Help that enumerates
  options is a promise about them.

### 8.2 A pre-existing wart, recorded and not fixed

`_print_report` (`src/codeatlas/cli/main.py:1312`) dispatches on `markdown` and
`sarif` and falls through to JSON for **anything else**. So
`codeatlas impact --format prr` prints JSON and reports success, and a fourth
format makes that typo more likely, not less.

This spec adds a `pr` branch and leaves the fallback alone. Making an unknown
format an error is a CLI behaviour change that could break a script relying on
the current leniency, and it is not what this slice is for. It is recorded in
`documentation/memory.md` as a follow-up.

Note the REST and MCP surfaces do not share the wart: both validate against a
`Literal` and reject an unknown value at the boundary.

## 9. Testing

**New unit suites**, which the delivery layer has never had:

- `markdown_text` — a value containing a pipe, a backtick, a backslash, an
  angle bracket, a newline and a control character survives escaping; a cell
  longer than `MAX_CELL_LENGTH` is truncated rather than wrapped; `table` emits
  a header, a separator, and one row per input with matching column counts.
- `pr_report` — the assertions below.

**The assertions that carry the product's honesty:**

- every impact edge renders its derivation;
- the gap disclaimer renders whenever any gap renders;
- a `GapReason` renders its code and explanation;
- `NO_TEST_FILE_REFERENCE` renders no evidence reference;
- an over-budget report declares what it omitted, and still contains its
  findings and gaps.

**Escaping parity.** One test renders the same report through both
`render_markdown` and `render_pr_markdown` and asserts a hostile symbol name is
escaped identically in each. That is the test that would fail if the two
renderers ever stop sharing `markdown_text`.

**Existing suites.** `tests/contract/test_change_cross_adapter.py` continues to
pass unchanged, and gains a case asserting the `pr` format is reachable through
REST, CLI, and MCP and returns the same content for the same analysis.

## 10. Definition of done

- `markdown_text.py` exists; both renderers import it; no escaping logic is
  duplicated.
- `render_markdown` renders each test gap's reason code, explanation, and
  evidence; its disclaimer is unchanged.
- `render_sarif` is unchanged.
- `render_pr_markdown` renders in the Section 5.1 order, keeps derivation on
  every impact edge, and always carries the gap disclaimer.
- The PR output contains no forge URL and no network access.
- Over-budget output declares its omissions and retains findings and gaps.
- `"pr"` works through REST, CLI, and MCP.
- Full quality gate green, with commands, exit codes, and output recorded.
- `contract_version` `1.1`, `SCHEMA_VERSION` `14`, no migration, no new
  dependency.
- `docs/operations/change-analysis.md` documents the new format and when to use
  it rather than `markdown`.
- `documentation/memory.md` updated and a handoff appended to
  `docs/plans/PLAN.md`.
