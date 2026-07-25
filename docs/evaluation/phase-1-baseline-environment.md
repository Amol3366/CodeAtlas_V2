# Phase 1 Baseline: Environment, Method, and How to Read It

Generated: 2026-07-25
Artifacts: `baseline-phase-1.json`, `baseline-phase-1.md`

## What this baseline is

The first measurement of a real CodeAtlas engine. Phase 0 recorded an honest
null baseline with no engine at all; this replaces it for the one capability
Phase 1 built.

**Targets are deliberately not enforced.** Phase 1 implements one of nine query
intents and no change analysis, so the Section 19.3 product targets cannot be
met and pretending otherwise would make the number useless. `targets_met` is
`false` and that is the correct result for this phase.

## Environment

- Windows 11, Windows PowerShell 5.1
- CPython 3.12 selected by `uv 0.11.24`
- `git version 2.55.0.windows.3`
- Dependencies frozen by `uv.lock`; `tree-sitter 0.26.0`,
  `tree-sitter-python 0.25.0`
- Parser bundle version `1.0.0`; index version `1.0.0`; contract version `1.0`

## Method

`scripts/run_phase1_baseline.py` loads the Phase 0 corpus, runs
`codeatlas.evaluation.engine_adapter.predict_exact_symbols`, and renders the
report. The adapter:

1. registers each supported fixture directory as a real repository in a
   throwaway SQLite database, indexes it, and queries it through the same
   application services the CLI and REST API use;
2. answers only cases whose intent is `EXACT_SYMBOL` on the `python_app`
   fixture, and emits an explicit abstention for every other case;
3. uses the case's declared expected symbol as the lookup term, because Phase 1
   has no natural-language intent classifier — this measures symbol resolution,
   which Phase 1 built, not question understanding, which it did not;
4. labels emitted evidence with the dataset's declared snapshot ID so it can be
   compared with the gold corpus, but only after the engine has validated that
   evidence against its own content-derived active snapshot.

Fixture repositories are read as data. Nothing in them is imported or executed.

Wall timings are **excluded** from the tracked artifact (`record_timings=False`).
They differ on every machine and every run, so including them would make a
committed baseline impossible to verify byte-for-byte. Correctness metrics are
unaffected. Performance is a separate measurement that must name its hardware,
repository profile, and cold/warm state, per `CLAUDE.md` Section 19.3.

## Results

| Metric | Value | Reading |
| --- | ---: | --- |
| Query cases | 40 | 5 answered, 35 abstained by design |
| Change cases | 24 | none attempted; Phase 4 scope |
| Exact symbol resolution | 0.1282 | 5 of 39 cases that declare an expected symbol |
| Primary evidence Recall@10 | 0.0635 | limited by the same 35 abstentions |
| Valid evidence rate | 0.8000 | see the warning below |
| Changed-symbol precision / recall | 0.0000 | no change analysis exists yet |
| Direct-impact recall | 0.0000 | no relation graph exists yet |
| Unsupported-claim rate | 0.0000 | no claim was made without evidence |

On the five supported cases the engine resolved **5 of 5** expected symbols.

## How to read `valid_evidence_rate = 0.8`

This metric counts predicted evidence whose `(snapshot, path, start_line,
end_line)` tuple exactly equals a gold tuple. **It does not measure whether the
evidence points at real lines of a real file.** Every evidence item the engine
emitted was checked against the fixture contents and all of them fall inside
their file's real bounds; none was invented.

The single miss is case `q009`, which expects lines 10–11 of
`src/payments/service.py` for `PaymentService.capture` while the engine returns
the symbol's full definition range, 7–11. Both point at the same real method.
The corpus asks for a sub-range of a definition; the engine currently emits
definition ranges.

| Case | Expected | Engine | Agrees |
| --- | --- | --- | --- |
| `q001` | `service.py` 3–11 | 3–11 | yes |
| `q002` | `service.py` 7–11 | 7–11 | yes |
| `q004` | `idempotency.py` 1–9 | 1–9 | yes |
| `q008` | `test_service.py` 7–9 | 7–9 | yes |
| `q009` | `service.py` 10–11 | 7–11 | no |

**The gold case was not edited to raise the metric.** Changing an expectation to
match the engine would destroy the corpus's value as an independent check. The
disagreement is recorded here and needs a product decision in a later phase:
either evidence gains sub-definition ranges, or `q009` is re-scoped, or the
metric distinguishes containment from exact equality.

## Reproducing

```powershell
uv run python scripts/run_phase1_baseline.py `
  --dataset tests/evaluation/cases `
  --json-output docs/evaluation/baseline-phase-1.json `
  --markdown-output docs/evaluation/baseline-phase-1.md `
  --check
```

`--check` compares against the tracked artifacts and exits 5 if they drift. Omit
it to regenerate intentionally, then review the diff.

## Accepted non-goals for this baseline

- no embeddings, reranking, or generation;
- no TypeScript, JavaScript, Markdown, or configuration parsing;
- no relations, graph traversal, or impact analysis;
- no change analysis, findings, or reports;
- no natural-language intent classification;
- no performance targets — timings here are informational only, taken on one
  machine against a tiny fixture.
