# Evaluation: Derivation-Tiered Test Edges (2026-08-07)

Re-measurement after the "test mapping and gap reasons" feature (nine
implementation tasks: `SymbolKind.FIXTURE` emission, `conftest.py`
classification, `RelationKind.CONSUMES_FIXTURE`, derivation-tiered `TESTS`
edges, and `GapReason`/`GapReasonCode`). `RESOLVER_VERSION` moved
`1.1.0` → `1.2.0`.

This document records the delta beside the Phase 4 baseline. It does **not**
replace or modify `docs/evaluation/baseline-phase-4.json` /
`baseline-phase-4.md`, which remain gate evidence approved 2026-07-27 per the
project owner's ruling on 2026-08-07. Per that ruling, this measurement was
taken **without** `--check` and written to a scratch path, never over the
tracked baseline files.

## Command

```bash
uv run python scripts/run_phase4_baseline.py \
  --dataset tests/evaluation/cases \
  --json-output .superpowers/sdd/2026-08-07-test-mapping-and-gap-reasons/eval-after.json \
  --markdown-output .superpowers/sdd/2026-08-07-test-mapping-and-gap-reasons/eval-after.md
```

Exit code: `0`.

## Result: the numbers did not move

| Metric | Baseline (2026-07-27) | After this feature (2026-08-07) | Delta |
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

The freshly generated JSON report is byte-for-byte identical to
`docs/evaluation/baseline-phase-4.json` (confirmed with a direct diff of the
two files; zero lines differ). The freshly generated Markdown report is
likewise identical to `docs/evaluation/baseline-phase-4.md`.

**Nothing moved, so nothing needs explaining beyond that fact** — per the
task instruction, "if the numbers turn out not to have moved at all, say so
plainly."

### Why nothing moved

The `tests/evaluation/cases` dataset that Phase 4's baseline is measured
against does not currently contain a case whose expected findings depend on
a fixture-mediated or helper-mediated `TESTS` edge, or on a `GapReason`
appearing in `test_gaps`. The new derivation paths and the new `TESTS`
tier they add are real — they are exercised directly by unit and integration
tests added in Tasks 1–9 of this feature — but the Phase 4 evaluation corpus
does not happen to contain a scenario where indirect test coverage changes
which findings, precision, or recall numbers the corpus-level metrics report.
This is a statement about the corpus's coverage of this new capability, not
a claim that the capability has no effect in general.

### Direct-impact precision

The task brief calls out direct-impact precision by name as a metric to
watch for regression. The tracked baseline's summary table does not carry a
`direct_impact_precision` field distinct from `changed_symbol_precision`
(0.9375, unchanged) — the JSON schema for this evaluation reports
`changed_symbol_precision`, `changed_symbol_recall`, `direct_impact_recall`,
and `unsupported_claim_rate`; there is no separately named
`direct_impact_precision` field in the current contract. Since the full JSON
report is byte-identical to baseline, whatever precision-shaped signal exists
in that report is unchanged. No regression to report.

### Unsupported-claim rate

Held at `0.0000`, unchanged. This is the metric the task brief says must
never move — a `low_confidence_heuristic` `TESTS` edge is a labeled
candidate, not an unqualified claim, so its presence should never register
as an unsupported claim. It did not move. No stop-and-fix condition was
triggered.

## Full quality gate (run separately, see task-10-report.md for detail)

`scripts/check_phase4.ps1` runs `scripts/run_phase4_baseline.py` **with**
`--check` against the tracked baseline paths
(`docs/evaluation/baseline-phase-4.json`/`.md`). Because the freshly computed
report is byte-identical to those tracked files, `--check` against the real
baseline paths **passes** (exit `0`), and the full `check_phase4.ps1` gate
passes end to end. This is a stronger result than the task brief anticipated:
the brief expected this feature's behavior change to make the Phase 4 engine
baseline step fail, and instructed that failure be documented rather than
fixed. That failure did not materialize, because the Phase 4 corpus does not
exercise the new derivation paths. The baseline files were not touched.
