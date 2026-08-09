# ADR-0027: Evidence recall is measured by containment

- Status: accepted
- Date: 2026-08-09
- Decision owners: user/product and implementing agent
- Supersedes: none
- Extends: ADR-0003 (evidence granularity), ADR-0023 (which moved the evidence
  *gate* to containment and left the recall metric behind)

## Context

`primary_evidence_recall_at_10` asks whether the answer's evidence surfaced in
the top ten results. It answers that question by comparing
`snapshot:path:start:end` strings for **exact equality**, so a citation one line
longer than the gold range is scored as though the evidence was never found.

On the Phase 7 conceptual corpus that is four of the five recorded misses:

| Case | Expected | Returned | Rank |
| --- | --- | --- | ---: |
| s001 | `src/orders/inventory.py:20-28` | contains it | **1** |
| s012 | `docs/runbook.md:3-6` | `docs/runbook.md:3-7` | **1** |
| s008 | `docs/architecture.md:14-18` | `docs/architecture.md:14-19` | **2** |
| s013 | `src/orders/models.py:6-12` | contains it | **4** |
| s007 | `src/orders/service.py:56-69` | absent | — |

Only **s007** is a retrieval failure. The other four return the right evidence,
three of them in the top two results, and score zero.

ADR-0003 already ruled on this. Graph and conceptual answers cite spans that
rarely coincide with a gold range written to describe a definition, so
`containing_evidence_rate` was introduced as the honest measure of validity and
`_contains` was written to implement it — directional, file-scoped, and refusing
a prediction that clips either end, because "a citation that omits part of the
answer has not proven it".

ADR-0023 then moved the evidence **gate** from `valid_evidence_rate` to
`containing_evidence_rate` on exactly that reasoning. It did not move the recall
metric. `primary_evidence_recall_at_10` sits beside `_containing_count` in the
same module and does not use it.

This is the shape this project keeps finding: a ruling applied to one surface
and not its neighbour. `SUPPORTED_FIXTURES` was maintained while
`SUPPORTED_INTENTS` was not (ADR-0017); the `GapReason` data reached the web
screen and no other renderer; `--format pr` was advertised in help and rejected
by the guard.

## Decision

**Add `containing_evidence_recall_at_10`, gate on it at the unchanged 0.90
threshold, and keep `primary_evidence_recall_at_10` reported and unchanged.**

The demand is unchanged — the answer's evidence must surface in the top ten.
Only the definition of *surfaced* is corrected, using the predicate ADR-0003
already defined rather than a new one.

Retaining the exact-match number is deliberate and follows ADR-0003's own
precedent, which kept `valid_evidence_rate` when `containing_evidence_rate`
arrived so that no historical number changed meaning. Six baselines carry
`primary_evidence_recall_at_10`; redefining it in place would silently change
what all six report. The two are published side by side because **the gap
between them is itself the measurement** — it says how precisely CodeAtlas can
point at an answer, as opposed to whether it found it.

One containment predicate serves both metrics. `_containment_keys` re-keys each
prediction by the expected range it contains, then feeds the existing
`ranked_metrics` and `_recall`, so there is a single definition of the ranking
arithmetic. A parallel Recall@K implementation that disagreed about duplicates
or the nDCG denominator would make the two numbers incomparable, which would
defeat the reason for publishing both.

## Measured

Phase 7 conceptual corpus:

| Metric | Deterministic | Semantic |
| --- | ---: | ---: |
| `primary_evidence_recall_at_10` (exact, retained) | 0.6000 | 0.6667 |
| `containing_evidence_recall_at_10` (gated) | 0.8667 | **0.9333** |

**The gate condition passes at 0.9333 against ≥ 0.90, and the deterministic side
does not.** The semantic layer carries the last 0.0667, which is the same
delta it contributed on the old metric — the uplift record is unchanged in
substance.

Phase 3 (0.4068) and Phase 4 (0.8136) rise and **still miss** the 0.90 target.
A correction that made every corpus pass would be a sign the definition had been
loosened rather than fixed.

## No engine behaviour changed

**Nothing in this record makes CodeAtlas better at finding evidence, and it must
never be cited as though it did.** No file under `src/codeatlas/` outside
`evaluation/` was touched. The retrieval, ranking, and evidence paths are
byte-identical. What changed is which question the metric asks.

Condition 7 of the Phase 7 gate has been recorded as missed since 2026-07-31.
This record is the reason it now passes, and the reason is a measurement
correction. **s007 remains a genuine retrieval miss and is not addressed here.**

## Alternatives

**Redefine `primary_evidence_recall_at_10` in place.** Rejected: six tracked
baselines carry that field, and changing its meaning without changing its name
makes every historical comparison silently wrong. ADR-0003 faced the identical
choice and kept both numbers.

**Leave the metric and fix retrieval instead.** Rejected on evidence. Four of
the five misses already return the right evidence at ranks 1, 1, 2 and 4; there
is no retrieval work that can improve a case whose answer is already at rank 1.
The only case retrieval can help is s007, worth 0.0667 on its own.

**Relax to overlap rather than containment.** Rejected, and pinned by a test. A
citation that clips either end of the answer has not proven it. Overlap would
reward a partial citation and is the loosening this record must not become.

**Lower the 0.90 threshold.** Rejected as the dishonest version of the same
outcome. The threshold is not what is wrong; the instrument is.

## Consequences

- `AggregateMetrics` gains one optional field, defaulted to `None`, so an
  artifact written before this record still loads and scores exactly as before.
- `QueryScore` and `ChangeScore` each gain a containment counterpart. Both sides
  feed one aggregate, so both use one rule; a mixed aggregate would mean two
  things at once.
- Five tracked baselines were regenerated for the added field:
  `baseline-phase-0`, `-3`, `-4`, `-7`, and `rerank-phase-7`.
  **`baseline-phase-1` and `-2` were deliberately not touched** — frozen history
  whose gate scripts are marked SUPERSEDED.
- The null baseline sets the new metric to `0.0` explicitly rather than
  inheriting `None`: "nothing is implemented, so nothing is found" is a
  different claim from "not measured", which is the distinction ADR-0024 exists
  to keep.
- Phase 7's remaining unmet target is `symbol_recall_at_10` (0.7857).

## Security and Privacy

None. Evaluation scoring reads a corpus already in the repository, moves no
data, and touches no provider, credential, or logging path.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`, `SCHEMA_VERSION` stays `14`, and the dataset contract stays `1.0`.
Rollback is reverting the commit and regenerating the five baselines; the
retained exact-match metric means no historical figure needs restating either
way.

## Approval

Approved by the user on 2026-08-09, who chose to correct the metric and address
the genuine s007 miss as a separate slice so the two causes stay attributable.
The corpus was **not** edited (ADR-0003).
