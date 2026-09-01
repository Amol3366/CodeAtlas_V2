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

## Measurement, 2026-09-01 (DR-02) — the first numbers taken on a real repository

The declared targets are scoped **"on the declared fixture and named hardware"**
(Phase 4 condition 7), and on that fixture they are met: preflight p95 5.151 s
against ≤ 10 s, refresh p95 1.426 s against ≤ 2 s. Nobody had ever measured a
real codebase, which is what the register row asked for. **Nothing below is a
gate result** — the gate is the fixture — and none of it changes the Phase 4
approval.

### Preflight on this repository, through the CLI

769 files, 727 parsed. Three runs each, an isolated database via `--db`.

| Operation | Median | p95 | Less CLI startup |
| --- | ---: | ---: | ---: |
| Commit-range preflight (`--commits HEAD~5..HEAD`) | 29.52 s | 29.70 s | **27.90 s** |
| Working-tree preflight | 34.29 s | 34.37 s | **32.67 s** |
| `codeatlas --help` (startup floor) | 1.62 s | 1.65 s | — |

Spreads were 29.39–29.70 s and 34.16–34.37 s, so these are not load artefacts.

**A real repository costs ~6.7x the fixture it was gated on.** Working-tree
runs cost 4.8 s more than commit-range because `analyze_working_tree` refreshes
the index before comparing (ADR-0063).

**The register's 10–12 minute `impact` observation is stale.** It was recorded
2026-08-13, five days before ADR-0064's 29x improvement, and is now ~20x wrong.

### The realistic corpus profile, and what the synthetic one hides

`measure_phase4_perf.py --profile realistic` emits Markdown that mentions the
symbols the modules define, so the reference class ADR-0064 found to dominate
real cost is present. The synthetic profile is unchanged and still produces the
tracked baseline. Both swept on one machine, `machine_settled: True` on all six
points, `--runs 3`.

| Modules | Synthetic preflight p95 | Realistic preflight p95 | Synthetic refresh p95 | Realistic refresh p95 |
| ---: | ---: | ---: | ---: | ---: |
| 40 | 0.911 s | 2.203 s | 0.417 s | 1.146 s |
| 80 | 1.362 s | 3.942 s | 0.599 s | **2.153 s** |
| 160 | 2.113 s | 7.452 s | 1.006 s | **4.587 s** |

**At 160 modules the realistic corpus costs 3.60x the synthetic one**, and the
log-log slope of preflight p50 against module count is **0.898 realistic against
0.602 synthetic** — half again as steep.

**Two cautions, stated rather than left for a reader to trip over.** These
exponents are **not comparable to ADR-0062's 1.14**: that sweep ran to 800
modules and this one stops at 160, where fixed costs still dominate and depress
every slope below 1. And the ≤ 2 s refresh target — fixture-scoped, met on the
fixture — is **missed on the realistic corpus from 80 modules upward**. That is
a statement about what the fixture cannot see, not a regression.

### Resolution's residual, profiled

ADR-0064 left it explicitly open: 3.55 s across 161,343 references "is not
obviously optimal". One working-tree preflight under `cProfile`, this repository.

**cProfile inflates the run to 90.5 s against 32.7 s unprofiled, so only the
proportions below are evidence.**

| Stage | Cumulative | Share |
| --- | ---: | ---: |
| `resolution.resolve` (3 calls) | 34.5 s | **38%** |
| — of which `_derive_config_edges` | 17.8 s (9.68 s self) | 20% |
| — of which `_resolve_mention` | 7.7 s | 9% |
| `sqlite3.executemany` | 18.6 s | **21%** |
| `ignore_rules.is_ignored` (`fnmatch` 5.7 s, `re.match` 6.4 s) | 8.6 s | 9% |
| `scanner.scan` | 7.2 s | 8% |
| `stable_hash` (488,397 calls, via `relation_id`) | 6.5 s | 7% |

**Resolution is still the largest stage, and `_derive_config_edges` is over half
of it** — the same site ADR-0064 de-quadraticised, still dominant afterwards.

**No optimisation is proposed here, and none is scheduled.** Committing to a fix
off one profile is what ADR-0060 through ADR-0062 did three times before
ADR-0064 measured properly. What the profile establishes is where a future task
should look, and that **two non-resolution costs are now comparable in size** to
the one everybody has been attacking: SQLite `executemany` at 21% and ignore-rule
matching at 9%. A task that optimises resolution alone would be attacking 38% of
the cost while ignoring 30% sitting beside it.
