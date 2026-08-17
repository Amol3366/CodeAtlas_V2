# ADR-0056: The coarse-chunk penalty is a pure loss, measured

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (accepted 2026-08-17) and implementing agent
- Supersedes: none — it *discharges* the measurement ADR-0030 demanded
- Related: ADR-0028 (rank fusion, which recorded the bias), ADR-0030 (s001 is a
  granularity disagreement), ADR-0046 (a module can answer a conceptual
  question), ADR-0003 (the corpus is never edited to move a number),
  ADR-0023 (target profiles)

## Context

ADR-0028 recorded, as a known and untuned limitation, that **reciprocal-rank
fusion rewards coarse chunks**: a whole-file chunk matches most queries, appears
in both channels, and the rank sum credits it for being unspecific. It
deliberately did not add a granularity penalty, calling it "a tuning knob that
needs its own evidence".

ADR-0030 then found the same bias attached to a concrete case (s001) and
declined to act, because the obvious lever "would **demote the very chunk
providing the rank-1 containment hit**" — an evidence hit traded for a symbol
hit. It required that any such change "be measured across the corpus, not fitted
to one case".

ADR-0046 ruled the product question underneath it — a module-level answer
satisfies a conceptual question — and **made no ranking change**, reframing the
remaining work from "fix the bias" to "measure whether the bias costs anything".

This record is that measurement.

## The premise this task carried was false

The work was scoped as measuring the bias **"now that the corpus is larger"**.
It is not larger. WS-1 grew `tests/evaluation/cases` from 27 to 50 scored
symbol-intent cases by adding the `symbol_breadth` fixture, and **fusion never
runs on that corpus**: `_fuse` is gated on `SEMANTIC_INTENTS`
(`{PROJECT_OVERVIEW, TEXT}`), and the Phase 4 baseline path
(`predict_exact_symbols`) attaches no fusion layer at all.

The only corpus that reaches fusion is `tests/evaluation/semantic_cases` —
**14 cases over one fixture** (`orders_service`), fed to `predict_conceptual` by
`run_phase7_baseline.py` alone. `git diff 38cc393 HEAD` reports its
`queries.json` and `changes.json` **byte-identical since 2026-07-31**; the sole
change anywhere in that tree is the two-line `target_profile` key ADR-0023
added.

So this is measured at exactly the corpus size ADR-0028 and ADR-0030 were
written against. **Another stale premise** — the program has now recorded one
under Tasks 1, 2, 3, 6 and both WS-1 sub-tasks, and **Task 4 remains the only
one whose premise checked out**. The conclusion below is unaffected, but the
number of cases behind it is 14, not 50, and it must not be quoted as though the
corpus had grown.

## What was measured

Two measurements, neither of which modifies `src/`.

**Incidence, observational.** `fuse_ranks` and `SemanticFusionService.augment`
were wrapped to record the *real* per-channel orders, so the data is the
engine's, not a reimplementation's. Granularity is read from the chunk's own
`SymbolKind` — `MODULE`/`CLASS`, the `_CONTAINER_KINDS` the chunker itself
uses — rather than an invented size threshold.

A coarse chunk outranks the expected evidence in **2 of 14 cases**: s007 (one
coarse chunk above rank 8) and s013 (one above rank 7). **Both remain inside the
top 10**, so the bias costs **zero** recall today.

**Effect, interventional.** The penalty was injected by wrapping `fuse_ranks` at
measurement time, at three strengths — because ADR-0028 rejected channel
weighting as "a constant nobody can later justify", and a result holding at one
arbitrary constant would repeat that mistake.

| Metric | baseline | scale 0.50 | scale 0.25 | fine-before-coarse |
| --- | ---: | ---: | ---: | ---: |
| `containing_evidence_recall_at_10` | **1.0000** | 0.9333 | 0.8667 | 0.8667 |
| `primary_evidence_recall_at_10` | **0.8000** | 0.7333 | 0.7333 | 0.7333 |
| `symbol_recall_at_10` | **0.9286** | 0.8571 | 0.8571 | 0.8571 |
| `mean_reciprocal_rank` | **0.6977** | 0.6888 | 0.6888 | 0.6888 |
| `ndcg_at_10` | **0.7530** | 0.7304 | 0.7304 | 0.7304 |
| `containing_evidence_rate` | 0.1116 | 0.1116 | 0.1116 | 0.1116 |
| `exact_evidence_rate` | 0.0605 | 0.0605 | 0.0605 | 0.0605 |
| `abstention_correctness` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

**Every metric that moves, moves down, at every strength. Nothing improves.**

## Decision

**Do not implement the coarse-chunk penalty. Close the item.**

ADR-0030 predicted a *trade* — an evidence hit lost for a symbol hit gained.
**There is no trade.** `symbol_recall_at_10` falls too, 0.9286 → 0.8571,
alongside every evidence metric. The lever loses on both sides of the exchange
it was supposed to balance.

The per-case ranks say why:

| Case | Expected evidence | baseline | 0.50 | 0.25 | fine-first |
| --- | --- | ---: | ---: | ---: | ---: |
| s001 | `src/orders/inventory.py:20-28` | **1** | 5 | 11 | 11 |
| s007 | `src/orders/service.py:56-69` | 8 | **7** | **7** | **7** |
| s013 | `src/orders/models.py:6-12` | 7 | 28 | 28 | 28 |

- **s001** is ADR-0030's prediction, now measured: the *only* region containing
  the expected range is the module chunk `inventory.py:1-36`. Penalising it
  drops the case's sole evidence out of the top 10 entirely.
- **s013 is the finding ADR-0030 did not anticipate.** The expected answer
  `OrderStatus` (`models.py:6-12`) **is itself a class chunk** — coarse by any
  definition that catches the chunk above it. The penalty demotes the very
  answer it exists to promote, 7 → 28.
- **s007 is the only gain in the corpus**: rank 8 → 7. It was already inside the
  top 10, so it cannot improve any Recall@10, and the ~0.001 it contributes to
  `mean_reciprocal_rank` is swamped by the losses — MRR still falls overall.

The result is not sensitive to where the coarse boundary is drawn. Both losses
occur because the *expected* chunk is coarse, so widening the definition can
only demote them further; the effect is monotone against the lever.

## The cheaper option is not available either

ADR-0046 permits *widening* a conceptual expectation to accept the module that
documents the concept, and the work plan named this as "also permitted by the
ruling, and cheaper". Applied to s001, **it is not permitted.**

ADR-0046 allows widening only on the ADR-0031/ADR-0036 justification: the
expectation named something the engine cannot produce, or contradicted itself.
s001 declares `InventoryLedger.reserve`, which the engine **does** produce — at
symbol rank 12. The expectation is neither impossible nor self-contradictory, so
widening it would be editing the corpus to move a number, which ADR-0003
forbids. **s001 stays as written.**

## Two corrections to the record

**ADR-0028's second recorded cost no longer reproduces.** It recorded s004 as a
regression: "the whole-file chunk `pricing.py:1-42` — which also contains the
expected range — now sorts above it". Today `tax_for` (`pricing.py:18-20`) is
rank **1** and `pricing.py:1-42` is rank **5**. Deliberately **not attributed**:
ADR-0026 (exact-match promotion) and ADR-0029 (`CHUNKER_VERSION` 1.0.0 → 1.1.0)
are both plausible and separating them needs a bisect this measurement did not
do. Recorded as a fact, not a cause.

**ADR-0028's first recorded cost is unchanged.** s013 measures rank 7, exactly
the "rank 4 → 7" it recorded.

## Why the instrument can be believed

**The unpenalised column reproduces the tracked artifact exactly.** Every one of
the eight baseline figures equals the semantic side of
`docs/evaluation/baseline-phase-7.json` to full precision — 1.0, 0.8,
0.9285714285714286, 0.6977040816326531, 0.7529705336309596,
0.11162790697674418, 0.06046511627906977, 1.0. The measurement is therefore
reading the same pipeline the gate reads, not a lookalike assembled here.

The per-case ranks were separately checked against three figures recorded
independently before this measurement existed, and agree with all three:

| Recorded | By | Measured now |
| --- | --- | --- |
| s013 fused rank 7 | ADR-0028 | 7 |
| s001 symbol rank 12 | ADR-0030 | 12 |
| `symbol_recall_at_10` 0.9286 | ADR-0030 | 0.9286 |

The penalty demonstrably changed behaviour at every strength, so this is not a
mutation that could not apply — the failure mode ADR-0055 recorded, where a
green result and an inapplicable mutation are indistinguishable.

## Stated limits of the measurement

- **14 cases, one fixture.** A bias that costs nothing here could cost something
  on a repository whose files are larger or whose modules are less well
  documented. This measures the corpus, not the world.
- Chunks that are not exactly a symbol range are classified coarse by a span
  threshold of 25 lines. One region falls near it (`docs/architecture.md:1-24`,
  a whole-file document chunk, classified fine). The conclusion does not turn on
  it, for the monotonicity reason above, but the threshold is an arbitrary
  constant and is recorded as one.
- Only the semantic corpus was measured, because it is the only corpus fusion
  runs on. This says nothing about ranking on lexical or symbol intents.

## Alternatives

**Implement the penalty anyway, tuned weaker than 0.50.** Rejected: the trend
across three strengths is monotone toward the baseline, so the best a weaker
constant can do is approach "no penalty" from below. There is no strength at
which it wins, only strengths at which it loses less.

**Widen s001's expectation.** Rejected above on ADR-0046's own justification
test.

**Grow the semantic corpus, then re-measure.** Not rejected — deferred. It is a
fixture-shaped workstream rather than a case, and nothing currently fails.

## Consequences

- **No source, corpus, contract, schema, or baseline file changes.** Every
  tracked metric is unchanged, because nothing in `src/` was modified.
- The RRF coarse-chunk row in the Deferred Register closes. Its trigger
  ("someone measures it corpus-wide") is discharged by this record.
- ADR-0028's coarse-chunk limitation keeps its warning value but loses its
  open-question status: the knob has now been turned, corpus-wide, and it is
  worse in every direction.
- `scripts/measure_rrf_penalty.py` is added so the measurement is a command
  rather than a day's work if the corpus ever grows. It is **not** in any gate:
  it needs the `semantic-local` extra, and §4.3 forbids making a gate depend on
  an optional provider — the same reason the explanation A/B was removed from
  `check_phase7.ps1` and left as a documented manual command.

## Security and Privacy

None. The measurement runs the local embedding provider already used by the
Phase 7 baseline; nothing is transmitted. No source, prompt, or answer content
is logged.

## Migration and Rollback

Not applicable. `contract_version` stays `1.1`, `SCHEMA_VERSION` stays `14`. No
behaviour changed, so there is nothing to roll back; reverting this record
removes a document and a manual script.

## Approval

**Approved by the user on 2026-08-17**, after the corpus-wide numbers at three
penalty strengths, the per-case ranks, and the three record corrections were
reported. The coarse-chunk penalty stays unimplemented, and the RRF row in the
Deferred Register is closed rather than re-deferred.

The measurement is reproducible with
`uv run python scripts/measure_rrf_penalty.py --ab`. Re-run it if the semantic
corpus ever gains a second fixture — the conclusion rests on 14 cases over one,
and that limit is recorded above rather than left implicit.
