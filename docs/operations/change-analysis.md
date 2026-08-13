# Change Analysis (Phase 4)

Status: current as of Phase 4
Audience: developers operating or extending the change-assurance engine

## What it does

`codeatlas impact <repository_id>` compares two states of a repository and
reports what changed, what may be affected, which findings that produces, and
the exact evidence for each — risk-ordered, snapshot-bound, and identical
through the application service, REST, the CLI, and MCP.

```powershell
uv run codeatlas impact <repository_id>                     # working tree vs HEAD
uv run codeatlas impact <repository_id> --base HEAD~1       # different base
uv run codeatlas impact <repository_id> --commits A..B      # commit range
uv run codeatlas impact <repository_id> --format sarif      # json | markdown | sarif
uv run codeatlas analysis <repository_id> <analysis_id>     # re-read a stored analysis
```

REST: `POST /v1/change-analysis/working-tree`,
`POST /v1/change-analysis/commits`, `GET /v1/change-analysis/{analysis_id}`,
`GET /v1/change-analysis/{analysis_id}/report`. MCP mirrors the same four
operations. Exit code 4 means the analysis ran and found nothing to report.

## The two flows

**Working tree.** Requires a Git repository (`CHANGE_ANALYSIS_REQUIRES_GIT`
otherwise). The freshness gate runs first: the tree is re-indexed so the
analysis never describes a repository that no longer exists; if indexing
fails, the analysis fails with it and the previous active snapshot is
untouched. The base side reads blobs at the base ref; the target side reads
the working tree.

**Commit range.** Both refs resolve through `git rev-parse --verify` with a
strict ref grammar (`GIT_REF_UNRESOLVABLE` on failure). Both sides are Git
blob states.

Base-side content is historical by construction and labeled `STALE`; the
side each evidence item came from is explicit (`AnalysisSide`), and a stored
analysis is an audit record that survives snapshot supersession. Deleting a
repository deletes its analyses.

## The engine

The engine itself never invokes Git: two `StateView`s go in (directory, Git
blobs, or stored snapshot), one report comes out, every stage timed:

```text
file diff -> parse+resolve both sides -> symbol diff -> body classification
          -> impact -> architecture rules -> findings -> risk
```

- **File diff** is content-hash based. A rename is claimed only on hash
  equality, or — when the content also changed — on a *uniquely* moved
  symbol pairing a deleted and an added file (both directions unambiguous).
  Git's similarity scores are never evidence.
- **Symbol diff** matches by `(kind, qualified_name)`: added, deleted,
  modified, moved, and dependency changes (content unchanged, resolved edge
  set or import binding different). Container folding reports one edit once:
  a deleted container carries its subtree, a type container absorbs member
  shape changes, and a code container speaks through its members.
- **Body classification** is syntax-level (`difflib` plus Python `ast` or
  tree-sitter statements) and labeled `high_confidence_heuristic`. On the
  Python path, a modified return or raise also carries a precise citation
  span: the changed statement plus the body statements sharing its names.
- **Impact** walks stored relations only, inbound for dependencies, both
  ways for path agreements (`ROUTES_TO`, `DOCUMENTS`, route-derived
  `REFERENCES`), one hop for `TESTS`, bounded (depth 3 default, caps on
  visited nodes and paths). Truncation is a warning plus a limitation, never
  silence. A deleted symbol's surviving referrers are reported as
  unresolved dependents. `TESTS` now carries two confidence tiers: a test
  that imports and calls the target directly is `high_confidence_heuristic`;
  a test that only reaches it through a fixture parameter or a helper call is
  `low_confidence_heuristic`, and still appears in impact citing the
  intermediate hop (see ADR-0016). `RelationKind.CONSUMES_FIXTURE` — a test
  requesting a fixture by parameter name — is stored and citable but is
  never walked during impact expansion; it names which fixture a test asked
  for, not what depends on what.
- **Findings** fire from a fixed rule table, one primary finding per changed
  symbol plus independent file/document/architecture rules. An extra
  plausible finding costs gate precision, so a rule fires only on what its
  conditions prove.
- **Risk** orders by severity, then derivation (deterministic outranks
  heuristic at equal severity), then stable keys; overall risk is the
  highest severity present, never arithmetic over counts.
- **Architecture rules** load from `.codeatlas/rules.toml` (stdlib
  `tomllib`; unknown fields refused). Only edges absent from the base graph
  are violations, so adopting rules mid-life does not bury a repository in
  its history.

## Test gap reasons

Every changed symbol with no qualifying `TESTS` edge is reported in
`test_gaps`. Each gap now also carries a `GapReason` naming why, not just
that: `FIXTURE_MEDIATED_ONLY` and `HELPER_MEDIATED_ONLY` cite the
low-confidence `TESTS` edge found one hop away (through a fixture or a
helper) as `evidence_ids`, so the report explains its strongest near-miss
instead of reporting bare absence; `IMPORTED_NOT_CALLED`,
`CALLED_NOT_IMPORTED`, and `NO_TEST_FILE_REFERENCE` cover the direct-path
failure modes. Finding a near-miss never removes the symbol from
`test_gaps` — a low-confidence edge explains a gap, it does not close it
(ADR-0016).

`test_gap_reasons` is an additive, optional field; `contract_version` stayed
`"1.1"`.

**How this is gated.** The Phase 4 corpus has no fixture- or helper-mediated
case, so it cannot exercise the ADR-0016 invariant at all — every case there
resolves through direct imports and calls, and nothing in that corpus moves
when the tiering breaks. A separate corpus at
`tests/evaluation/invariant_cases/` does exercise it, checked by
`scripts/check_invariants.py` and recorded in `docs/evaluation/invariants.json`.
Four cases run against one fixture tree whose four changed symbols are each
reachable by exactly one path: fixture-mediated (`Order`), helper-mediated
(`total`), a strict import-and-call edge that must still close a gap
(`unused_helper`), and a symbol no test references (`audit`). One tree rather
than four proves the reasons discriminate between each other in a single run.

Regenerate the artifact by running the script without `--check`. A broken
invariant exits 7; a stale artifact exits 5. The two are deliberately
separate: one says the product regressed, the other says regenerate the file.

This corpus asserts a boolean, never accuracy. A case about how *well*
something is detected belongs in the Phase 4 corpus instead.

**Reindex requirement.** `RESOLVER_VERSION` moved `1.1.0` → `1.2.0` because
resolution now derives `CONSUMES_FIXTURE` and the two new `TESTS` tiers,
which it did not derive before. Every snapshot resolved under `1.1.0` is
stale for this feature's purposes: it will not carry the new edges or the
new gap reasons until re-indexed. The working-tree freshness gate re-indexes
automatically; a stored analysis or a snapshot that predates the resolver
bump is reported with a limitation from the resolver-staleness guard
(`change_analysis.py`) rather than silently under-counting test coverage.

## Reports

JSON is the contract (`change_analysis_report` in
`docs/api/contract-v1.schema.json`). Markdown escapes every interpolated
value for the construct it lands in — repository text cannot become table
structure, close a code span, or move a terminal cursor. SARIF 2.1.0 is an
export: repository-relative URIs only, and a finding with no citable
location produces no result rather than an invented one.

### `text` — for a terminal, and `impact`'s default

`codeatlas impact` prints this. It is a verdict, not a document: a risk line
with counts, findings ordered most severe first, and possible test gaps with
the reason each is still a gap. Impact is a count rather than a table, but the
`low_confidence_heuristic` count is named — a weak edge is a candidate, not
coverage, and a summary that hid the distinction would undo ADR-0016.

No colour is used. `documentation/design.md` requires that colour is never the
only signal, and not depending on it is the simplest way to satisfy that — it
also means the output is identical piped, redirected, or captured by CI, with
no terminal detection to get wrong.

`codeatlas analysis` still defaults to `markdown`: it prints a stored record,
which is the archival case.

### `pr` — for pasting into a pull request

`markdown` is the audit format: complete, flat, every evidence row present,
ordered for the record. `pr` is the same analysis ordered for a reviewer.

It leads with the risk verdict and the counts, then the two things a reviewer
must act on — findings, risk-ordered, and possible test gaps with the reason
each is still a gap. Changed symbols, impact edges, and the evidence table
follow inside `<details>` blocks. Warnings and limitations are never collapsed:
they qualify everything above them, and a qualification behind a disclosure
triangle is one most readers never see.

Impact edges keep their derivation inside the collapsed block. A
fixture-mediated `TESTS` edge carries `low_confidence_heuristic`, so "a test you
should probably run" cannot read as "a test that covers this" — see ADR-0016.

**Bounded, and any cut is declared.** The output is capped at 60,000
characters — a conservative bound, not any platform's limit. Findings and test
gaps are never what gets cut; supporting detail is dropped whole-section from
the end, and the report ends with a line naming exactly what was omitted and
pointing at `markdown` or `json` for the complete analysis. Leaving it
unbounded would not be safer: the destination would truncate it arbitrarily,
mid-sentence, with no notice.

It contains no forge URLs and posts nothing. A permalink needs a host, owner,
repository and commit that CodeAtlas does not have, and a guessed one is a
citation pointing at the wrong code.

**Which to use.** `pr` for a human reading a review. `markdown` for a complete
archival record. `json` for anything scripted — it is the contract, and the
only format with stability guarantees.

Available identically through REST (`?report_format=pr`), the CLI
(`--format pr`), and MCP (`report_format: "pr"`).

## Running it from the CLI

```
codeatlas impact <repository-id>                 # working tree vs HEAD
codeatlas impact <repository-id> --since main    # everything on this branch
codeatlas impact <repository-id> --commits A..B  # one commit range
codeatlas impact <repository-id> --fail-on high  # exit 7 at or above high
```

`--since`, `--commits`, and `--base` are mutually exclusive; passing two is
refused rather than resolved by a precedence rule the caller cannot see.

**`--since main` is not `--base main`.** It analyses from the *merge base* of
that ref and `HEAD`. A two-dot diff against a trunk that has moved would report
the trunk's own new commits as changes to your branch, inverted.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The analysis ran. With `--fail-on`, nothing met the threshold. |
| `2` | Invalid input — an unknown `--format`, an unknown `--fail-on` severity, or conflicting range selectors. |
| `3` | A required resource was unavailable. |
| `4` | The analysis ran and found nothing to report. **A clean change returns 4, not 0** — this predates `--fail-on` and is unchanged by it. |
| `5` | A policy failure, such as a path outside the repository root. |
| `6` | An internal failure. |
| `7` | `--fail-on` was given and a finding met or exceeded that severity. |

`7` is separate from `5` deliberately: a CI job must be able to tell "your
change is risky" from "you pointed me at the wrong directory", which need
opposite responses. And `--fail-on` always prints the report before setting the
code — a CI log showing only a failure number is not diagnosable.

## Performance

Two numbers are measured by `scripts/measure_phase4_perf.py` and recorded
with hardware in `docs/evaluation/phase-4-baseline-environment.md`:
changed-file incremental refresh (target p95 ≤ 2 s) and warm working-tree
preflight (target p95 ≤ 10 s). Git blob states prefetch the whole tree with
one `git archive` call (byte-identical to per-blob reads, asserted by test)
instead of two subprocesses per file.

## What Phase 4 does not do

- The engine parses **both full states** on every analysis. Resolution needs
  a complete symbol table; the cost is O(repository), not O(change), and the
  snapshot-reuse path decision 2 describes is not implemented.
- Commit-range analysis never reuses the active snapshot, even when a side's
  commit matches it.
- Statement classification says nothing about runtime behavior, and TS/JS
  classification is coarser than the Python `ast` path (whole-symbol
  citations).
- Route and document edges are name-shaped heuristics; framework routing is
  not runtime-resolved, and neither edge kind may support a claim alone.
- `ARCHITECTURE_RULE_VIOLATED` has no independent corpus case; it is proven
  by unit and integration tests only.
- Rename detection needs a unique moved symbol or hash equality; a rewritten
  file that keeps no symbol identity is a delete plus an add.
- **A file that is tracked by Git but excluded from indexing is invisible to
  preflight** — it can be added or deleted without a finding (ADR-0044). Both
  sides of a comparison now list only what a scan would index, because a file
  that is excluded has no symbols and no evidence to cite, and reporting on it
  would mean reporting something no answer could support. Before that record
  such a file was in the base and not the target, which is indistinguishable
  from a deletion: an unmodified checkout of this project reported 26
  `SYMBOL_DELETED` findings at **high** severity. A reviewer who cares about
  committed build output must look at Git.
- **A tracked file larger than `max_file_bytes` (2 MB) fails the analysis
  outright**, rather than being skipped the way the directory scan skips it.
  One committed 3 MB CSV therefore makes a repository impossible to preflight.
  This is open and recorded in the Deferred Register; today's behaviour is
  pinned by a test so it cannot change silently while the ruling is pending.
- Line endings are normalized on both sides, so a change that is *only* line
  endings reports nothing (ADR-0043). Intentional, and the same answer Git
  gives under `text=auto`.
