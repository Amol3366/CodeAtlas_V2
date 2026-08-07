# CLI impact UX

Status: approved design, not yet implemented
Date: 2026-08-08
Authority: `AGENTS.md` is the contract. This spec is subordinate to it.
Related: ADR-0005 (change assurance), ADR-0016 (derivation-tiered test edges),
and the PR-export spec of 2026-08-07.

## 1. Why

`documentation/PRD.md` calls change preflight "the product". Typing
`codeatlas impact` is the shortest path to it, and today that path prints the
full audit Markdown — headings, tables, and an evidence dump — into a terminal.
The rendering is correct and complete. It is not a verdict.

This slice makes the bare command answer the question a developer actually has
("should I worry, and about what?"), adds the two flags that let a script ask
the same question, and fixes a defect shipped in the previous slice.

## 2. A live defect, fixed first

`codeatlas impact --format pr` and `codeatlas analysis --format pr` both exit
with `INVALID_REQUEST` while their own `--help` advertises `pr`.

Each command carries its own allow-list — `{"json", "markdown", "sarif"}` at
`src/codeatlas/cli/main.py:1249` and `:1297`. The PR-export slice added `pr` to
the help strings and to `_print_report`, and updated neither guard.

The cross-adapter test written in that slice asserted REST and MCP returned
identical `pr` output. It never invoked the CLI, which is exactly why the guard
was never exercised.

The one-value fix is trivial. The fix that matters is a test **parameterised
over every format the help text advertises**, so the next format added fails
loudly if a guard is missed rather than silently in a user's terminal.

### 2.1 A correction to the record

`documentation/memory.md` and the 2026-08-07 `PLAN.md` handoff both record a
follow-up stating that `_print_report` silently falls through to JSON for an
unknown `--format`.

**That defect does not exist.** Both commands validate before reaching
`_print_report`, so its `else` branch is unreachable from either. The real
defect was the opposite — a valid format rejected — and it went unrecorded while
an imagined one was written down twice.

Both entries are corrected rather than deleted. The record should show what was
believed and what turned out to be true.

## 3. Scope

**In scope.** The §2 fix and its parameterised test; a `text` renderer and its
adoption as `impact`'s default; `--fail-on`; `--since`; a `merge_base` method on
the Git adapter; documentation.

**Out of scope.** Colour or terminal styling (Section 5.2). Progress spinners.
Watch mode. Any change to `render_markdown`, `render_pr_markdown`, or
`render_sarif`. Any change to the analysis engine: every value rendered here
already exists on `ChangeAnalysisReport`.

**Out of scope, permanently.** Any claim that a symbol is tested or untested.

## 4. Exit codes

The CLI's vocabulary is fixed at `src/codeatlas/cli/main.py:77-82`: `0` success,
`2` invalid input, `3` unavailable, `4` partial, `5` policy failure, `6`
internal failure.

`impact` currently exits **`4` when there are no findings** — its docstring
states that "the analysis ran and found nothing to report" is a different fact
from a failure. A consequence is that a clean change returns non-zero, so
`codeatlas impact && deploy` fails on exactly the changes that are safe.

That is surprising, and this spec does **not** change it. Some script may
already depend on it, and silently redefining a documented exit code is a
breaking change dressed as an improvement.

Instead:

```python
EXIT_RISK_THRESHOLD = 7
```

Returned **only** when `--fail-on` is passed *and* a finding meets or exceeds
the threshold. Without the flag, every exit code behaves exactly as it does
today.

`EXIT_POLICY_FAILURE` (`5`) is deliberately not reused: it already means
`PATH_NOT_ALLOWED`, `PATH_OUTSIDE_ROOT`, and `SCAN_LIMIT_EXCEEDED`. A CI job
must be able to tell "your change is risky" from "you pointed me at the wrong
directory" — two failures that need opposite responses.

### 4.1 The severity ordering `--fail-on` needs, and its second duplication

`_SEVERITY_ORDER` — the tuple ordering `Severity` from critical to info — exists
twice: `src/codeatlas/delivery/markdown_report.py:29` and
`src/codeatlas/delivery/pr_report.py:26`. The PR-export slice introduced the
second copy. A `text` renderer would make a third.

That slice was careful to extract the *escaping* into one module for exactly
this reason and then duplicated the ordering in the same commit. Three copies of
"which severity is worse" is three places for them to disagree about it.

It moves to `src/codeatlas/contracts.py`, immediately after the `Severity` enum:

```python
SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)
```

`contracts.py` rather than a delivery module because the ordering is a property
of the severity vocabulary itself, not of any rendering — and `--fail-on`
(Section 6) needs it too, from outside `delivery` entirely.

Additive: a new module-level constant changes no model and no
`contract_version`. Both renderers import it and delete their local copies;
their behaviour is unchanged.

## 5. `text` — a rendering for a terminal

A fifth format, `src/codeatlas/delivery/text_report.py`, exposing
`render_text(report: ChangeAnalysisReport) -> str`.

### 5.1 Shape

```
HIGH risk · 8 symbols across 12 files · 3 findings · 2 possible test gaps
base HEAD (a1b2c3d, fresh) → working tree

FINDINGS
  HIGH   Public contract changed          PUBLIC_CONTRACT_CHANGED
         orders.Order.total signature changed
         src/orders.py:40-52 (target) · static_resolved · 0.90

POSSIBLE TEST GAPS
  A missing TESTS edge does not prove absence of coverage.
  CodeAtlas does not execute tests.

  orders.Order    reached only through a fixture   FIXTURE_MEDIATED_ONLY
```

Verdict first, then findings risk-ordered, then gaps with their reasons. No
tables, no HTML, no evidence dump — a terminal is not a document, and the
formats that are documents already exist.

Impact edges are **summarised, not listed**: a count, plus the count of edges
carrying `low_confidence_heuristic`. The full list is what `--format markdown`
is for. Where an edge is named at all, its derivation is named with it.

### 5.2 No colour

Severity is rendered as a word. Colour is not used at all — not as decoration
and not as signal.

`documentation/design.md` requires that colour is never the only signal, and the
simplest way to satisfy that in a terminal is not to depend on it. It also keeps
output identical when piped, redirected, or captured by CI, without any
`isatty` branching to test.

### 5.3 The gap disclaimer

Whenever any gap is rendered, the text output carries the meaning fixed in
`src/codeatlas/delivery/markdown_report.py`: a missing `TESTS` edge does not
prove absence of coverage, and CodeAtlas does not execute tests. The heading
says "POSSIBLE TEST GAPS". Never "UNTESTED".

### 5.4 It becomes `impact`'s default

`--format markdown` still produces today's output byte-for-byte for anyone who
wants it, and `analysis` keeps `markdown` as its default — that command prints a
stored record, which is the archival case.

Changing what a bare `impact` prints is a real change for anyone reading it. It
is not a contract change: human-readable CLI output has never been one, which is
what `--format json` is for.

## 6. `--fail-on <severity>`

Accepts `critical`, `high`, `medium`, `low`, `info` — the `Severity` values.
Exits `EXIT_RISK_THRESHOLD` when any finding's severity is at or above the
given level, using the existing severity ordering rather than a second copy of
it.

An unrecognised value is `INVALID_REQUEST` with the accepted values listed. It
does not fall back to a default: a typo in a CI configuration must fail loudly,
not quietly disable the check it was meant to enforce.

`--fail-on` never suppresses output. The report prints, then the exit code is
set — a CI log that shows nothing but a failure code is not diagnosable.

## 7. `--since <ref>`

`--since main` analyses the merge-base of `<ref>` and `HEAD` through to `HEAD` —
"everything on my branch, ignoring what the trunk did meanwhile".

A ref is required. This spec does not guess a trunk name: a repository without
`main` is not this tool's business to assume about, and guessing wrong would
silently analyse the wrong range.

### 7.1 Why it needs a Git adapter method

`--since main` is **not** `--base main`. A two-dot diff against a trunk that has
moved reports the trunk's own new commits as changes to your branch, inverted.
Only a merge-base gives "what I changed".

`GitDiffAdapter` gains:

```python
def merge_base(self, root: Path, ref: str) -> str
```

running `git merge-base <ref> HEAD` through the existing argument-array
subprocess path — never a shell — and validating the ref with the adapter's
existing `_validate_ref`. An unresolvable ref surfaces as
`GIT_REF_UNRESOLVABLE`, the code that path already uses.

### 7.2 Mutual exclusion

`--since`, `--commits`, and `--base` are mutually exclusive. Passing more than
one is `INVALID_REQUEST` naming the conflict.

A silent precedence rule would mean a user who passed both got an analysis of a
range they did not ask for, and had no way to know.

## 8. Testing

**`text_report`** gets its own unit suite. Two assertions carry the product's
honesty and must not be weakened: the gap disclaimer renders whenever a gap
does, and every named impact edge carries its derivation.

**The CLI**, in `tests/contract/` — where `test_maintenance_cli.py` and
`test_settings_cli.py` already live:

- **Parameterised over every format the help text advertises**, asserting each
  exits `0` on a real analysis. This is the test whose absence caused §2, and it
  is the most valuable test in this slice.
- `--fail-on high` exits `7` with a high finding present, and `0` with only a
  low one.
- `--fail-on nonsense` exits `2` and names the accepted values.
- Without `--fail-on`, exit codes are unchanged — including `4` for no findings.
- `--since` and `--commits` together exit `2`.
- `--since <ref>` produces the same report as `--commits <merge-base>..HEAD`.

**`merge_base`** gets an integration test over a real Git repository with a
diverged trunk — the case where it differs from a two-dot diff, and therefore
the only case that proves it was worth adding.

## 9. Definition of done

- `--format pr` works on both `impact` and `analysis`, proven by a test
  parameterised over the advertised formats.
- The false follow-up in `documentation/memory.md` and the 2026-08-07 `PLAN.md`
  handoff is corrected, and the real defect recorded.
- `SEVERITY_ORDER` lives once, in `contracts.py`; both existing renderers import
  it and no local copy remains.
- `render_text` exists; `impact` defaults to it; `--format markdown` output is
  unchanged byte-for-byte; `analysis` still defaults to `markdown`.
- The gap disclaimer is present in text output whenever a gap is.
- `--fail-on` exits `7` at or above threshold, `0` below, `2` on a bad value,
  and never suppresses output.
- `--since` uses a real merge-base; `--since`/`--commits`/`--base` conflicts
  exit `2`.
- No colour, no `isatty` branching.
- `render_markdown`, `render_pr_markdown`, and `render_sarif` unchanged,
  verified by an empty diff.
- Full quality gate green, with commands, exit codes, and output recorded.
- `contract_version` `1.1`, `SCHEMA_VERSION` `14`, no migration, no new
  dependency.
- `docs/operations/change-analysis.md` documents the exit codes and the new
  flags; `documentation/memory.md` updated and a handoff appended to
  `docs/plans/PLAN.md`.
