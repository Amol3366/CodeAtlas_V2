# An invariant corpus for ADR-0016

Date: 2026-08-08
Status: approved, not yet implemented

## The problem

ADR-0016 states the governing rule of tiered test edges: **a weak edge
explains a gap rather than closing it.** A test that reaches a changed symbol
only through a fixture parameter or a helper call produces a
`low_confidence_heuristic` `TESTS` edge, which appears in impact and supplies
a `GapReason` — but never removes the symbol from `test_gaps`.

The 24-case Phase 4 evaluation corpus contains no fixture-mediated and no
helper-mediated scenario. Every case resolves through direct imports and
calls. So when the tiering shipped, no evaluation metric moved, and
`scripts/check_phase4.ps1` reports green on an invariant it cannot exercise.

The behaviour is real and covered by unit and integration tests. What is
missing is a gate that fails when the invariant is broken by someone who is
editing those tests anyway.

## Why this is a second surface, not an extension of the first

The Phase 4 corpus answers "how accurate is change assurance across 24
representative cases?" — a measurement that legitimately moves as the engine
improves. This asks something different: "does a weak edge still refuse to
close a gap?" — a boolean that must never change.

Conflating them is what created the collision. `ChangeCase`
(`src/codeatlas/evaluation/dataset.py:93`) has no field for test gaps, and
`ContractModel` is `extra="forbid"`, so a case cannot carry one until the
model does. Adding a gap metric to the report model would alter
`baseline-phase-4.json`'s shape and break the byte-for-byte `--check` that
must keep passing — before a single case was added.

Keeping the surfaces separate means the Phase 4 corpus, dataset models,
evaluation runner, report model, baselines, and existing gate steps are
untouched **by construction**, not by care.

## Layout

```
tests/evaluation/invariant_cases/
  cases.json                                   declarative expectations
  fixtures/
    orders/{base,target}/                      one tree, four changed symbols
scripts/check_invariants.py                    the checker
docs/evaluation/invariants.json                committed result artifact
docs/evaluation/invariants.md                  the human reading
```

All four cases share **one** committed pair of directories, in the layout the
`python_app` fixture already uses (`src/`, `tests/`). Four separate trees would
each prove a reason in isolation; one tree proves the four reasons
*discriminate between each other* in a single engine run, which is what the
precedence logic actually has to get right. The source shapes are carried from
`tests/integration/test_fixture_test_mapping.py`, where they are already proven
to produce one distinct reason each. The `fixture` field stays per-case so a
later invariant can add its own tree without restructuring the corpus.

No Git, no database, no state materialisation:
the engine is called directly with a `DirectoryStateView` per side, which is
exactly what `predict_changes`
(`src/codeatlas/evaluation/engine_adapter.py:469`) does after it materialises
its overlays.

Artifact filenames are stable rather than dated. They must reproduce, so a
date in the name would make every regeneration a new file instead of a diff.

## The corpus schema

Deliberately **not** `ChangeCase` — extending that model is the thing that
breaks the Phase 4 baseline. A separate, minimal contract:

```json
{
  "contract_version": "1.0",
  "cases": [
    {
      "id": "i001",
      "invariant": "a fixture-mediated symbol stays a gap",
      "fixture": "orders",
      "expect_gap_reasons": { "Order": "FIXTURE_MEDIATED_ONLY" },
      "expect_not_gaps": []
    }
  ]
}
```

`expect_gap_reasons` maps a qualified name to the `GapReasonCode` that must be
reported for it. Both halves are asserted: the symbol must be in `test_gaps`,
**and** the reason must match. Checking only membership would pass if the
reason logic collapsed to a single constant.

`expect_not_gaps` names symbols that must **not** appear in `test_gaps`.
Without it, a bug that made every symbol a permanent gap would satisfy every
other assertion in the corpus. This field is what proves the strict path still
closes a gap, and it is the reason case i003 exists.

Qualified names are bare — `Order`, not a module-prefixed path — as
`test_fixture_test_mapping.py` confirms. They are verified against the engine
during implementation rather than trusted from this document.

## The four cases

| Case | Symbol | Shape | Asserts |
| --- | --- | --- | --- |
| i001 | `Order` | Requested through a root `conftest.py` fixture parameter | `FIXTURE_MEDIATED_ONLY`, still a gap |
| i002 | `total` | Reached through a module-local helper in the test file | `HELPER_MEDIATED_ONLY`, still a gap |
| i003 | `unused_helper` | Imported and called directly by a test | `expect_not_gaps` — the strict path still closes |
| i004 | `audit` | Referenced by no test at all | `NO_TEST_FILE_REFERENCE` |

i001 and i002 are the two scenarios the Phase 4 corpus lacks and the reason
this work exists. i003 is the control. i004 anchors the bare-absence arm of
`GapReasonCode`, which is what the other three must not collapse into.

`IMPORTED_NOT_CALLED` and `CALLED_NOT_IMPORTED` are covered by unit tests and
are not given corpus cases: they are direct-path failure modes, not the
weak-edge invariant this corpus exists to defend.

## The checker

`scripts/check_invariants.py`, mirroring `scripts/run_phase4_baseline.py`'s
flags and exit codes exactly — `--corpus`, `--json-output`,
`--markdown-output`, `--check` — so it reads as machinery the repository
already has rather than a new idea.

It loads the corpus, and for each case calls:

```python
report = ChangeAnalysisEngine().analyze(
    DirectoryStateView(base), DirectoryStateView(target)
)
```

then compares `report.impact.test_gaps` and `report.impact.test_gap_reasons`
against the expectations, and writes both artifacts. `--check` compares
against the committed artifacts and exits non-zero on any difference.

A case the engine cannot run is recorded as a failure, never skipped —
"did not hold" and "was not measured" must not produce the same result at a
gate. This matches the rule `predict_changes` already documents for its own
unrunnable cases.

## Why the artifact makes this stronger than the test we already have

`tests/integration/test_fixture_test_mapping.py` covers the same behaviour
today. Its weakness is that it is an assertion inside a file that a refactor
touching this area is already editing — the guard and the thing it guards
move together.

Here, weakening the invariant requires **two visible acts in one diff**:
editing declarative corpus data, and regenerating a committed artifact.
Neither is something a person does without noticing, and neither is something
a reviewer reads past. This is the same shape as `baseline-phase-0/3/4`,
which is why it needs no new reviewer habit.

## Gate wiring

A step in `scripts/check_phase4.ps1`, after the Phase 4 baseline step, using
the existing `Invoke-Checked` helper:

```powershell
Invoke-Checked "ADR-0016 invariants" @(
    "run", "python", "scripts/check_invariants.py",
    "--corpus", "tests/evaluation/invariant_cases",
    "--json-output", $InvariantsJson,
    "--markdown-output", $InvariantsMarkdown,
    "--check"
)
```

with `$InvariantsJson` / `$InvariantsMarkdown` added as parameters alongside
the existing baseline path parameters.

It belongs in this script because change assurance is the script's subject
matter and this is the script run for this area — a separate script would be
one more thing to remember to run, which is the failure mode this work exists
to remove.

Plus one pytest that invokes the checker **in-process without `--check`**, so
a plain `uv run pytest` catches a broken invariant without needing the full
gate. It holds no expectations of its own — it asserts only that every case
in the corpus held — so it cannot be weakened without weakening the corpus.

## Tooling configuration

The fixture trees contain files named `test_*.py`. Three tools must be told
they are data, exactly as the existing corpus fixtures are
(`pyproject.toml`):

- `[tool.pytest.ini_options] norecursedirs` — otherwise pytest collects the
  fixture tests as part of the real suite
- `[tool.ruff] exclude` — otherwise lint fails on deliberately minimal code
- `[tool.mypy] exclude` — otherwise strict type checking fails on the same

Each gets one entry: `tests/evaluation/invariant_cases/fixtures/`. Fixtures
live under a `fixtures/` subdirectory precisely so these three excludes read
consistently with the four pairs already listed, and so `cases.json` stays
outside the excluded path.

## Explicitly out of scope

No change to `ChangeCase`, the evaluation runner, any existing metric, the
report model, or `baseline-phase-4.json` / `.md`. Verified by empty diffs on
those paths.

No new dependency. No contract version change — `contract_version` stays
`"1.1"`; the corpus carries its own independent `"1.0"`.

The corpus does not measure accuracy and must not grow into an accuracy
corpus. If a case is about how well something is detected rather than whether
the invariant holds, it belongs in the Phase 4 corpus instead.

## Documentation

- `docs/operations/change-analysis.md` — a short subsection under "Test gap
  reasons" naming the corpus, the checker, and how to regenerate the artifact
- `docs/adr/0016-derivation-tiered-test-edges.md` — a line recording that the
  invariant is now gated, and where
- `documentation/memory.md` — close the recorded open item; the corpus gap it
  describes is the thing this work fixes
- `docs/plans/PLAN.md` — appended handoff entry, never rewritten
