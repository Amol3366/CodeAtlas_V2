# ADR-0024: A Case the Adapter Never Ran Is Not a Wrong Answer

- Status: accepted
- Date: 2026-08-09
- Decision owners: user (approved taking the lexical retrieval work, and the sequencing), implementing agent (record)
- Supersedes: none
- Extends: ADR-0017 (the fixture gate), ADR-0023 (target profiles)

## Context

`engine_adapter`'s module docstring has said this since Phase 1:

> Every case outside that scope is emitted as an explicit abstention rather than
> a zero score, because "not implemented" and "answered wrongly" are different
> facts and the baseline must not blur them.

The adapter kept that promise. **The scorer broke it.** A case the adapter
declined to run was emitted as an abstention with no ranked symbols, and
`score_query_case` then recorded `exact_symbol_resolved=False` — landing in the
denominator as a wrong answer, indistinguishable from the engine getting it
wrong.

ADR-0017 found one half of this and fixed it by widening `SUPPORTED_FIXTURES`,
because most of the excluded fixtures were excluded by neglect. But
`malicious_unsupported` is excluded **on purpose** — it carries prompt-injection
text, and what the engine should return for hostile input is a security
question the accuracy corpus must not answer by side effect. Its cases kept
scoring as misses.

The consequence surfaced immediately when ADR-0023 added `lexical_resolution`.
That metric has ten scored cases, and **two of them (q037, q039) are on
`malicious_unsupported`** and can never pass. The maximum achievable value was
**8/10 = 0.80**, against a gate set at **0.90**. No engine could clear it.

That threshold was chosen in ADR-0023, hours earlier, by the same author. It was
recorded as provisional, and the reason it was wrong is not the number: it is
that a metric containing structurally unpassable cases cannot be reasoned about
at all.

## Decision

**1. `QueryPrediction` gains `measured: bool = True`.** The adapter sets it
`False` for a case it declined to run — an unsupported intent, or a fixture kept
out of the accuracy corpus on purpose. It defaults to `True`, so an existing
prediction file parses unchanged and every case in it stays scored exactly as
before.

**2. An unmeasured case is excluded from every accuracy aggregate**, not scored
as zero: `exact_symbol_resolution`, `lexical_resolution`, `symbol_recall_at_10`,
`mean_reciprocal_rank`, `ndcg_at_10`, `primary_evidence_recall_at_10`,
`relation_path_correctness`, and `abstention_correctness`.

Evidence *counts* need no filter: an unmeasured case predicts nothing, so it
contributes zero to both numerator and denominator already.

**3. `abstention_correctness` excludes them too, and that lowers the credit
available.** An unmeasured case abstained because the adapter declined to run
it, not because the engine judged its evidence insufficient. Counting it as a
correct abstention credits the engine for a decision it never made. q040
(`expected_abstention: true`, on `malicious_unsupported`) was scoring as a
correct abstention and no longer does.

**4. An engine abstention is still a miss**, and a test pins it. The
distinction only helps if the other side of it bites: a case the engine ran and
could not answer is a real failure, and excluding those would let any metric
improve by refusing to answer.

## Consequences

Every accuracy metric rises, because unmeasured cases were dragging all of them
down:

| Metric | Before | After |
| --- | ---: | ---: |
| `lexical_resolution` | 0.3000 | **0.3750** (3/8) |
| `symbol_recall_at_10` | 0.6923 | 0.7714 |
| `mean_reciprocal_rank` | 0.7692 | 0.8571 |
| `ndcg_at_10` | 0.7097 | 0.7908 |
| `primary_evidence_recall_at_10` | 0.6984 | 0.7458 |
| `relation_path_correctness` | 0.2917 | 0.3182 |
| `abstention_correctness` | 0.8750 | 0.9714 |
| `exact_symbol_resolution` | 1.0000 | 1.0000 (unchanged — all its cases were measured) |

**No engine behaviour changed.** Numbers rose because cases the engine was never
shown stopped counting against it. Anyone quoting this movement as an
improvement in CodeAtlas would be wrong.

`baseline-phase-3` and `-4` regenerated. `baseline-phase-7` is unchanged —
`predict_conceptual` has no fixture gate, so it has no unmeasured cases. The
Phase 0 null baseline is unchanged, because it reports a `not_implemented` run
whose metrics are fixed at zero by construction.

### This was done first, deliberately

The lexical work that prompted it is a parser change: nested configuration keys
(`service.port`, `features.audit`) are computed by `_nested_paths` and then
flattened into a display string, so they never become addressable symbols and a
config lookup can only return the parent key. Fixing that will move
`lexical_resolution` again.

Doing the scoring correction first means that movement is measured against a
denominator that is honest. Doing it second would have measured an engine
improvement against a metric already known to be broken, and the two causes
would have been impossible to separate.

### Still open

`lexical_resolution` now has **eight** scorable cases, so every value it can
take is a multiple of 0.125. A gate at 0.90 therefore means "8 of 8" and
nothing else — it cannot express any intermediate standard. The threshold needs
setting to a value the metric can actually take, and that should wait until the
nested-key work lands so it can be chosen against real per-case evidence rather
than guessed a second time.
