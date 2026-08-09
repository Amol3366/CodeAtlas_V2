# ADR-0028: Both retrieval channels are fused by rank

- Status: accepted
- Date: 2026-08-09
- Decision owners: user/product and implementing agent
- Supersedes: none
- Overturns: the ordering rule asserted by
  `test_deterministic_evidence_keeps_its_place_and_its_derivation`, recorded
  below rather than quietly amended

## Context

The task was "fix s007" — `OrderService.cancel` was absent from the top 10 for
*"What happens to held stock if somebody changes their mind?"*, the one genuine
retrieval miss left after ADR-0027.

It could not be fixed by retrieval work, because retrieval was not what failed.
**The semantic channel already ranked the answer 8th.** The fused response put
it 16th.

`SemanticFusionService.augment` did two things that combined badly:

1. appended semantic candidates *after* every deterministic item, so a
   candidate could never outrank a lexical hit however well it matched; and
2. dropped any candidate the deterministic half had already cited.

A chunk both channels found therefore kept its lexical position and gained
nothing. The code's own comment said *"the two channels finding the same chunk
is the point of fusing them"* — and then discarded exactly that.

The measured cost, per channel, on the Phase 7 conceptual corpus:

| Case | Semantic rank | Fused rank |
| --- | ---: | ---: |
| s003 `shipping_for` | **1** | 5 |
| s007 `OrderService.cancel` | **8** | 16 |

s003 is the ranking weakness ADR-0022 recorded as *"one genuine engine
weakness"* and attributed to lexical matching on the word "customer". It was
this. **Two separately-recorded engine defects were one fusion defect.**

The semantic layer could only ever help chunks lexical search missed entirely,
which is why its measured uplift was +0.07.

## Decision

**Order conceptual answers by reciprocal-rank fusion over both channels.**

`score(item) = Σ 1 / (k + rank)` across the channels that returned it, `k = 60`.
Implemented as `application/rank_fusion.fuse_ranks`, a pure function with its
own unit tests, so the rule has one definition and is testable without a
repository.

Four properties are decided deliberately and pinned by tests:

- **Ranks only, never scores.** A BM25 score and a cosine distance are not
  comparable quantities; combining them directly would invent a number that
  means nothing. Rank is the one thing both channels express in the same units,
  which is also why this needs no per-channel calibration constant.
- **Ties resolve to the deterministic order.** When the evidence is indifferent
  between two items, the answer should be the one that does not depend on a
  model.
- **A channel does not corroborate itself by repeating.** Duplicates within one
  channel contribute one term, so a retrieval defect that lists a chunk twice
  cannot outrank genuine agreement between channels.
- **An empty semantic channel leaves the order untouched**, so removing the
  layer restores the exact prior answer — the subtraction-proof property the
  fusion suite already tests end to end.

Fusion happens **after** reranking, not before. The first implementation built
the channel order from the raw candidates, which let fusion re-sort the reranked
items back into their original order — the reranker's entire output computed and
then discarded by the next step. A test caught it. That is the same
"data computed, then not surfaced" shape as ADR-0020, ADR-0019, and ADR-0025.

## Section 4.3, and the invariant this overturns

Section 4.3 forbids a model score **promoting a probabilistic candidate to
deterministic evidence**. This does not do that. Every evidence object is
carried across unchanged and only its position moves: a `semantic_candidate`
stays a candidate wherever it lands, and the derivation ladder still decides
what may support a finding. `rank_fusion` cannot alter a label — it never sees
one.

**A documented invariant is nevertheless overturned on purpose.**
`test_deterministic_evidence_keeps_its_place_and_its_derivation` asserted the
deterministic prefix survived byte-for-byte, arguing that reordering it would be
the semantic layer *"deciding relevance, which is the authority it does not
have"*. That reading is now rejected: **order is not authority.** Presenting a
worse-matching citation first is not a trust property, it is a worse answer.
The test is rewritten to assert what the principle actually protects — every
deterministic item survives fusion present and unaltered — and its docstring
records that it used to say the opposite.

Scope is bounded by the existing gate: `_fuse` runs only for
`SEMANTIC_INTENTS`. Exact-symbol lookups, graph traversals, and change analysis
are never reordered, so no deterministic *resolution* is affected.

## Measured

Phase 7 conceptual corpus, semantic side, before and after:

| Metric | Before | After |
| --- | ---: | ---: |
| `containing_evidence_recall_at_10` | 0.9333 | **1.0000** |
| `symbol_recall_at_10` | 0.7857 | **0.8571** |
| `mean_reciprocal_rank` | 0.4429 | **0.6875** |
| `ndcg_at_10` | 0.5271 | **0.7292** |
| `primary_evidence_recall_at_10` | 0.6667 | 0.7333 |
| `exact_evidence_rate` / `containing_evidence_rate` | — | **unchanged** |

**The evidence rates not moving is the correct signature for a pure reorder**:
the same evidence, in a better order. Contrast ADR-0025, where recall rose and
span precision fell because the evidence set itself changed.

s007 enters the top 10 at rank 8. s003 moves 5 → **1**.

## Costs, stated

Two cases rank worse, and both were examined before the decision rather than
discovered after:

- **s004** `tax_for` is first in *both* channels and stays found, but the
  whole-file chunk `pricing.py:1-42` — which also contains the expected range —
  now sorts above it.
- **s013** rank 4 → 7. The semantic channel does not find `OrderStatus` at all,
  so mixing its opinion in dilutes a working lexical result.

Neither costs recall; both remain inside the top 10, which is why Recall@10
reaches 1.0 regardless.

**RRF rewards coarse chunks.** A whole-file chunk matches most queries, so it
appears in both channels and the rank sum credits it for being unspecific — this
is what put `tests/test_pricing.py` first for s004. A granularity penalty was
**deliberately not added**: it is a tuning knob that needs its own evidence, and
adding it here would bundle an unmeasured change with a measured one. Recorded
because it will resurface.

## Alternatives

**Corroboration only** — promote items found by both channels, keep
semantic-only candidates at the tail. A more conservative reading of §4.3. Not
chosen: it would fix s003 but leaves s007's fate unmeasured, and it introduces a
two-tier rule where one rule suffices.

**Leave fusion append-only.** Rejected on evidence: s007 and s003 are both
unfixable by any amount of retrieval work while the ranking signal is discarded.

**Weight the channels.** Rejected as premature. RRF needs no weights, and a
weight introduced without evidence is a constant nobody can later justify.

## Consequences

- Conceptual answers may now cite a `semantic_candidate` first. Its derivation
  is what keeps that honest, and it is exactly why the ladder exists.
- `symbol_recall_at_10` is Phase 7's only remaining unmet target, at 0.8571
  against 0.90. s013 and s001 are its residue.
- **Neither channel retrieves `OrderStatus` directly** — both reach it only via
  the containing `models.py` chunk. That is a chunking or extraction question
  about enums, independent of fusion, and is left open rather than folded in.
- The reranker's contract is unchanged and its test now isolates it from
  fusion, which is a sharper assertion than the one it replaced.

## Security and Privacy

None. Fusion reorders results already retrieved and validated inside the
process. No new data movement, no provider call, no logging change.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`, `SCHEMA_VERSION` stays `14`. Rollback is reverting the commit and
regenerating `baseline-phase-7`; no stored data encodes the ordering.

## Approval

Approved by the user on 2026-08-09, after reviewing the two regressions on
request and with the recall and MRR figures in hand. The corpus was **not**
edited (ADR-0003).
