# Task 10 Report: Quality gate, evaluation, ADR-0016, documentation

Branch: `test-mapping-and-gap-reasons`. Commit: `db6dc05`.

## Step 1: Full quality gate

```
uv run ruff check src tests scripts
```
First run: exit 1. Two findings, both in `tests/unit/test_impact.py`
(leftover from Task 9's end-to-end test, not this task's own change):
- `F401 HELPER_HINT imported but unused` (line 32)
- `E501 line too long (89 > 88)` (line 104)

Fixed both (removed the unused import; wrapped the long line). Re-run: exit 0,
"All checks passed!"

```
uv run mypy --no-incremental src
```
Exit 0. "Success: no issues found in 140 source files"

```
uv run pytest -q
```
Exit 0. `1974 passed, 3 skipped in 363.03s (0:06:03)`. The 3 skips are
`test_embedding_providers.py` cases that skip because `semantic-local` *is*
installed in this environment (inverse-condition skips, expected). No
`.test-tmp` WinError 32 flake observed in this run.

## Step 2: Re-run the evaluation

```
uv run python scripts/run_phase4_baseline.py \
  --dataset tests/evaluation/cases \
  --json-output .superpowers/sdd/2026-08-07-test-mapping-and-gap-reasons/eval-after.json \
  --markdown-output .superpowers/sdd/2026-08-07-test-mapping-and-gap-reasons/eval-after.md
```
Exit 0 (no `--check`, scratch paths only, baseline untouched).

## Step 3: The deltas

| Metric | Baseline (2026-07-27) | After (2026-08-07) | Delta |
| --- | ---: | ---: | ---: |
| Query cases | 40 | 40 | 0 |
| Change cases | 24 | 24 | 0 |
| Exact symbol resolution | 0.3846 | 0.3846 | 0 |
| Primary evidence Recall@10 | 0.5556 | 0.5556 | 0 |
| Valid evidence rate | 0.6610 | 0.6610 | 0 |
| Exact evidence rate | 0.6610 | 0.6610 | 0 |
| Containing evidence rate | 0.7458 | 0.7458 | 0 |
| Changed-symbol precision | 0.9375 | 0.9375 | 0 |
| Changed-symbol recall | 1.0000 | 1.0000 | 0 |
| Direct-impact recall | 1.0000 | 1.0000 | 0 |
| Unsupported-claim rate | 0.0000 | 0.0000 | 0 |

Verified with a direct diff (`json.dumps(..., sort_keys=True)` comparison and
`fc /b`) that `eval-after.json` is byte-for-byte identical to
`docs/evaluation/baseline-phase-4.json`, and likewise for the Markdown.
**The numbers did not move at all.** Per the task instruction, that fact is
stated plainly and nothing further needs documenting about the delta itself
(explanation of *why* nothing moved is still recorded, below and in the new
evaluation doc).

**Why nothing moved:** `tests/evaluation/cases` (the 24 change cases) does
not contain a scenario whose expected findings depend on a fixture-mediated
or helper-mediated `TESTS` edge, or on `GapReason` content in `test_gaps`.
The new derivation paths are real — exercised directly by unit/integration
tests from Tasks 1-9 — but this particular 24-case corpus doesn't happen to
touch them. This is a corpus-coverage gap, not evidence the feature has no
effect.

**Direct-impact precision:** not separately reported as a named field in
this evaluation's contract (only `direct_impact_recall` exists alongside
`changed_symbol_precision`/`recall`); since the full report is
byte-identical to baseline, no precision-shaped signal changed. No
regression found, so no finding to report here beyond noting the field
doesn't exist under that exact name.

**Unsupported-claim rate:** held at `0.0000`. No stop-and-fix condition
triggered.

### An unexpected result: the full gate actually passes

I additionally ran `--check` against the real tracked baseline paths
(read-only comparison — `--json-output docs/evaluation/baseline-phase-4.json
--markdown-output docs/evaluation/baseline-phase-4.md --check`, which
compares in-memory computed text against the existing file content without
writing): **exit 0**. I then ran the full gate script:

```
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1
```

**Exit 0.** Every stage passed: frozen dependency sync, contract schema
freshness, tests (1952 passed under the frozen/no-extras environment —
lower count than the 1974 above because `uv sync --all-groups --frozen`
uninstalled the optional semantic-local extras, changing which tests
collect), lint, types, dataset validation, Phase 0 baseline, Phase 3
baseline, and **Phase 4 baseline with `--check`** ("Phase 4 verification
completed.").

This contradicts the task brief's stated expectation ("that gate step is
expected to fail"). It did not fail, because — as established above — the
Phase 4 corpus doesn't exercise the code paths this feature added. I did not
"fix" anything to make it pass; it passed on the first real run because the
byte comparison genuinely matched. I did **not** modify
`docs/evaluation/baseline-phase-4.json`/`.md` at any point — confirmed via
`git status --short docs/evaluation/` showing no changes to those files
after the check.

After the gate run I restored the dev environment with
`uv sync --all-groups --all-extras` (exit 0) since the frozen sync had
removed `sentence-transformers`, `torch`, etc.

## Step 4-5: Documentation written

- `docs/adr/0016-derivation-tiered-test-edges.md` (new) — covers
  `CONSUMES_FIXTURE` as an intermediate, non-impact relation kind and the
  accepted cost of a framework-specific concept in a language-neutral enum;
  derivation-tiered `TESTS`; and the governing principle that a weak edge
  explains a gap rather than closing it. Extends ADR-0004, does not
  supersede it.
- `docs/evaluation/test-mapping-2026-08-07.md` (new) — the numbers above with
  every (non-)movement explained, plus the `check_phase4.ps1` full-pass
  finding.
- `docs/operations/change-analysis.md` (modified) — added `TESTS` tiering
  and `CONSUMES_FIXTURE`'s impact exclusion to the Impact bullet; added a new
  "Test gap reasons" section covering `GapReason`/`GapReasonCode` and the
  `RESOLVER_VERSION` reindex requirement.
- `documentation/architecture.md` (modified) — `Relation` bullet in Data
  Model now covers `TESTS` tiering, `CONSUMES_FIXTURE`, `SymbolKind.FIXTURE`
  emission, and `conftest.py` classification.
- `documentation/memory.md` (modified) — appended to Completed with the
  feature summary, gate results, and the evaluation surprise.
- `docs/plans/PLAN.md` (modified) — appended (not rewritten) a new handoff
  entry at the top of the Handoff Log, dated after the existing most-recent
  entry.

## Step 6: Commit

```
git add docs/ documentation/ tests/unit/test_impact.py
git commit -m "docs: ADR-0016 and evaluation record for derivation-tiered test edges" ...
```
Two pre-existing unrelated working-tree changes (`README.md` modification,
new `documentation/codeatlas-v2-working-guide.md`) present before this task
started were deliberately left uncommitted/unstaged — they belong to earlier
unrelated work, not this task.

Exit 0. Commit `db6dc05`, 7 files changed, 494 insertions(+), 4 deletions(-).

## Findings to report (not fixed)

1. The anticipated Phase 4 `--check` failure did not occur; the full gate
   passes. This is reported per the brief's instruction to say so plainly
   when numbers don't move, and is not something to "fix" toward failure.
2. The Phase 4 evaluation corpus has a coverage gap: no case exercises
   fixture-/helper-mediated `TESTS` edges or `GapReason` content. Recorded
   as a limitation, not addressed in this task (out of scope — corpus
   extension is separate work).
3. Fixed two pre-existing ruff findings in `tests/unit/test_impact.py`
   (unused import, line length) that were blocking gate green; these were
   lint-only fixes, no assertions changed.

## Surprises

- Byte-for-byte identity between the fresh evaluation run and the tracked
  baseline, given nine implementation tasks changed real behavior, was
  unexpected until traced to corpus coverage.
- The frozen `uv sync --all-groups --frozen` step inside `check_phase4.ps1`
  strips optional embedding extras, changing the pytest collection count
  (1974 vs 1952) — expected script behavior, not a defect, but worth noting
  for anyone comparing pytest counts across the two invocations in this
  report.

## Final review fix wave

Two review findings fixed, one test added, no other changes.

### Finding 1: NO_TEST_FILE_REFERENCE could assert a false claim

`src/codeatlas/analysis/impact.py`, `_gap_reason` fallback branch: changed
explanation text from "No test file references this symbol." to "No test
file imports or calls this symbol." Added a comment explaining that
`imports`/`calls` only inspect IMPORTS/CALLS, while `incoming` indexes every
resolved relation kind (e.g. INHERITS, REFERENCES), so the old text could be
false (e.g. a test class inheriting from the changed symbol). Enum member
`GapReasonCode.NO_TEST_FILE_REFERENCE` unchanged.

Also updated `docs/superpowers/specs/2026-08-07-test-mapping-and-gap-reasons-design.md`
line 208 table entry from "No test file references this symbol at all" to
"No test file imports or calls this symbol".

### Finding 2: stale HELPER_HINT docstring

`src/codeatlas/domain/relations.py`: `HELPER_HINT` docstring changed from
"Reserved for a later derivation pass; not yet produced anywhere." to "A weak
`TESTS` edge derived by following a test-helper call." (matches `FIXTURE_HINT`
style), since `_derive_helper_test_edges` in
`src/codeatlas/extraction/resolution.py` now produces it.

### Test added

`tests/unit/test_impact.py`:
- `test_an_inherit_only_test_reference_is_not_claimed_absent`: changed symbol
  reached only by an INHERITS edge from a test file. Asserts gap reason is
  `NO_TEST_FILE_REFERENCE` with explanation exactly "No test file imports or
  calls this symbol." and that it does not say "references this symbol".
- `test_a_production_call_is_not_reported_as_called_not_imported`: changed
  symbol reached only by a CALLS edge from production code. Asserts reason is
  `NO_TEST_FILE_REFERENCE`, not `CALLED_NOT_IMPORTED`.

### Mutation-check evidence for test (b)

Temporarily removed `and from_test(relation)` from the `calls` comprehension
only, ran:

```
uv run pytest tests/unit/test_impact.py::test_a_production_call_is_not_reported_as_called_not_imported -v
```

Result: FAILED —

```
E       AssertionError: assert <GapReasonCode.CALLED_NOT_IMPORTED: 'CALLED_NOT_IMPORTED'> is <GapReasonCode.NO_TEST_FILE_REFERENCE: 'NO_TEST_FILE_REFERENCE'>
```

Restored `and from_test(relation)`, reran the full suite:

```
uv run pytest tests/unit/test_impact.py tests/integration/test_fixture_test_mapping.py -v
```

Result: `37 passed in 2.15s`.

### Verification commands (final state)

```
uv run pytest tests/unit/test_impact.py tests/integration/test_fixture_test_mapping.py -v
```
-> 37 passed in 2.15s (exit 0)

```
uv run mypy --no-incremental src
```
-> Success: no issues found in 140 source files (exit 0)

```
uv run ruff check src tests
```
-> All checks passed! (exit 0)
