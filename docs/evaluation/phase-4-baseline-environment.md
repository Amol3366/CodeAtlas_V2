# Phase 4 Baseline and Performance Environment

Status: recorded 2026-07-27
Baseline artifacts: `baseline-phase-4.json`, `baseline-phase-4.md`
Regenerate or verify: `uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases --json-output docs/evaluation/baseline-phase-4.json --markdown-output docs/evaluation/baseline-phase-4.md [--check]`

## How to read the baseline

The Phase 4 baseline runs **both** prediction adapters over one corpus load:
the query cases through `predict_exact_symbols` (unchanged since Phase 3) and
the 24 change cases through `predict_changes`, which materializes each case's
two states as directories and runs the real `ChangeAnalysisEngine` — no Git,
no database, the same code the product flows use.

Because the two prediction sets are pooled, the *evidence* metrics
(`valid_evidence_rate`, `exact_evidence_rate`, `containing_evidence_rate`,
`primary_evidence_recall_at_10`) cover query and change evidence together and
therefore differ from the query-only Phase 3 report. Query-only metrics
(`exact_symbol_resolution`) are identical between the two reports, which is
the check that pooling changed accounting, not behavior.

## Phase 4 gate metrics, stated honestly

| Metric | Value | Target | Met |
| --- | ---: | ---: | --- |
| Changed-symbol recall | 1.0000 | ≥ 0.95 | yes |
| Changed-symbol precision | 0.9375 | ≥ 0.95 | **no — see below** |
| Direct-impact recall | 1.0000 | ≥ 0.90 | yes |
| Finding precision (per-case, evidence-supported) | 1.0000 | — | yes |
| Unsupported-claim rate | 0.0000 | < 0.02 | yes |
| Change-side evidence | every finding cites evidence exactly matching the declared corpus rows (all 24 cases) | 100% valid | yes |

### The precision miss, precisely

Changed-symbol precision is 0.9375 because c020, c021, and c022 each score
0.50, and the cause is structural, not a defect. The three cases share one
physical diff of the `git_changes` fixture — `base/service.py` (holding
`process` and `legacy`) becomes `target/processor.py` (holding a changed
`process`; `legacy` is gone) — and the corpus deliberately splits that one
diff into three single-symbol observations: c020 declares only `process`
(rename + signature), c021 only `legacy` (deletion), c022 only `process`
(optional parameter). The engine, run on identical state pairs, honestly
reports both affected symbols every time; each case then counts the other
case's symbol as a false positive. Per-case finding precision is still 1.0000
for all three, because finding support is evidence-filtered per case.

Per ADR-0003 the corpus is never edited to meet a number, and suppressing a
true changed symbol to score better would be exactly the dishonesty the gate
exists to catch. The miss is reported as a miss; every one of the remaining
21 cases scores 1.0000 on both precision and recall.

## Performance measurement

Measured with `scripts/measure_phase4_perf.py` (deterministic synthetic
repository, real Git, real indexing and analysis services on a temporary
SQLite database), 2026-07-27:

```text
uv run python scripts/measure_phase4_perf.py --modules 300 --runs 20
```

| Quantity | Value |
| --- | ---: |
| Repository profile | 300 generated Python modules, 3 packages, cross-package imports and calls |
| Cold full index | 8.32 s |
| Changed-file refresh p50 / p95 (warm, 20 runs) | 1.263 s / **1.426 s** (target ≤ 2 s: met) |
| Working-tree preflight p50 / p95 (warm, 20 runs) | 4.836 s / **5.151 s** (target ≤ 10 s: met) |

Hardware and software: 13th Gen Intel Core i7-13700HX, 16 GB RAM, Windows 11
Home Single Language 10.0.26200, Python 3.12.12, repository and database on
the same local disk. Method: each warm run edits one function body (a
different edit per run) and times the full service call, including the
freshness re-index inside the preflight. p95 is the 19th of 20 ordered
samples.

What the measurement includes and excludes:

- The preflight number includes ref resolution, the freshness gate's
  incremental re-index, base-blob reads, both full parses, resolution,
  diffing, impact, findings, persistence, and report construction.
- Base blobs are prefetched with a single `git archive` invocation
  (byte-identical to per-blob reads, asserted by test). Before that change
  the same measurement was ~8 s at only 30 modules — two Git subprocesses
  per file dominated everything.
- The engine still parses both full states per analysis (O(repository), not
  O(change)); that is the headroom cost recorded in
  `docs/operations/change-analysis.md`, and the snapshot-reuse path remains
  future work.
- Timings exclude machine-noise mitigation beyond repetition: no other
  significant load ran during measurement.

The tracked baseline artifacts exclude timings entirely so `--check`
reproduces byte-for-byte on any machine.

## Correction, 2026-08-08 — the query-side numbers in this file moved (ADR-0017)

The gate table above is the record of the 2026-07-27 approval and is
deliberately unedited. This section records that four of the query-side numbers
in `baseline-phase-4` have since changed, and why that is a measurement
correction rather than an engine change.

`predict_exact_symbols` gated whole cases out of the measurement by repository
fixture, and a gated case scores `False` rather than being excluded — so it
counted as a miss the engine never had a chance to make. The gate had been
frozen since Phase 1 while the engine gained TypeScript (Phase 3) and Git
(Phase 4), so 16 of 39 scored query cases were never run.

| Metric | Gate record (2026-07-27) | Corrected (2026-08-08) |
| --- | ---: | ---: |
| Exact symbol resolution | 0.3846 | 0.6154 |
| Primary evidence Recall@10 | 0.5556 | 0.6508 |
| Valid / exact evidence rate | 0.6610 | 0.6618 |
| Containing evidence rate | 0.7458 | 0.7353 |

**Every change-side metric is unchanged** — changed-symbol precision 0.9375,
changed-symbol recall 1.0000, direct-impact recall 1.0000, finding precision
1.0000, unsupported-claim rate 0.0000. The Phase 4 gate was approved on the
change-side numbers, and none of them moved, so the approval stands unaffected.

The claim above that "query-only metrics (`exact_symbol_resolution`) are
identical between the two reports" still holds: Phase 3 and Phase 4 both now
report 0.6154, and that cross-check is what confirms the correction changed
accounting rather than behavior.

Full rationale, including why `baseline-phase-1` and `baseline-phase-2` were
deliberately **not** regenerated, is in `docs/adr/0017-evaluation-fixture-gate-correction.md`.

## Correction, 2026-08-08 (second) — graph cases now declare their subject (ADR-0018)

The correction above was incomplete. `_query_term` also fed
`expected_symbols[0]` to the engine as the *subject* of a graph query, but for a
relation query `expected_symbols` is the answer and the subject is not in it.
Six cases now declare `query_subject`.

| Metric | ADR-0017 | ADR-0018 |
| --- | ---: | ---: |
| Exact symbol resolution | 0.6154 | 0.6667 |
| Primary evidence Recall@10 | 0.6508 | 0.6984 |
| Valid / exact evidence rate | 0.6618 | 0.6400 |
| Containing evidence rate | 0.7353 | 0.7067 |

**Recall rose and evidence-span precision fell, for the same reason.** Asking
the correct subject returns more evidence — the supporting relation edges — and
per ADR-0003 a call-site line rarely equals a gold range describing a
definition, so the additional items enlarge the denominator without matching
spans exactly. Any claim quoting one of these two movements must quote the
other.

Change-side metrics are again unchanged, so the Phase 4 gate approval remains
unaffected. ADR-0018 also records the two findings this exposed and deliberately
did not fix: module-scoped graph queries ranking the module's own symbol first,
and `related_tests` not resolving a method subject to its class-level edge.
