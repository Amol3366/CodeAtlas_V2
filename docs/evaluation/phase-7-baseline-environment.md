# Phase 7 baseline environment and how to read the numbers

Companion to `baseline-phase-7.{json,md}`. Section 19.3 requires a performance
claim to name its hardware and method; this document does the same for a
*correctness* claim, because the Phase 7 numbers are easy to quote in a way
that is technically true and materially misleading.

## What was measured

- Corpus: `tests/evaluation/semantic_cases`, 14 conceptual query cases and 1
  change case over the `orders_service` fixture (14 files, 114 chunks, 100
  symbols).
- Engine: `predict_conceptual`, which asks each question **verbatim** through
  `AnswerPipeline`. The Phase 1–4 adapter substitutes the declared symbol for
  the question, which measures resolution rather than understanding; doing that
  here would hand the answer to both sides and guarantee a tie.
- Provider: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, CPU,
  `l2_v1` normalization. Real model, real LanceDB-shaped vector interface (the
  in-memory store, which the LanceDB suite holds to identical behaviour).
- Both sides ran in the same environment with `--extra semantic-local`
  installed. The deterministic side does not use it, but running the two sides
  in different environments would compare things differing in more than the
  switch.
- Timings excluded, so the artifact reproduces byte-for-byte. Verified: a
  second run passes `--check`, including the model's embeddings.

## The gold was declared before the measurement

ADR-0003's rule. The 14 cases and their gold ranges were authored by reading
the fixture source, committed to `queries.json`, and validated with
`run_evaluation.py validate` **before** any engine was run against them. They
have not been edited since. Where the engine disagrees with a gold range, the
record stands.

## Read the delta, not the columns

The headline is **+0.0667 primary evidence Recall@10** (0.6000 → 0.6667).

An earlier draft of this measurement reported **0.0000 → 0.7333**, which was
wrong in the most flattering possible direction, and the reason is worth
keeping:

`build_match_expression` joined every term with `AND`, function words included.
No chunk contains all twelve words of "How do we stop two shoppers buying the
last one of something?", so **every** natural-language question returned zero
evidence. The deterministic baseline was not 0.0000 because deterministic
retrieval cannot answer conceptual questions; it was 0.0000 because of a defect
on the path that answers them — one that was live in the chat surface, where
`Intent.TEXT` is the classifier's fallback.

P7-06 fixed that first (relaxed-fallback pass, `LEXICAL_QUERY_RELAXED`) and
then measured. The fix is worth more than the feature it was blocking:

| Change | Recall@10 gain |
| --- | ---: |
| Fixing the lexical stopword defect | **+0.53** |
| Adding the entire semantic layer on top | **+0.07** |

Quoting the semantic layer's uplift against the *unfixed* baseline would credit
it with the lexical fix's work.

## The cost side is part of the result

Semantic retrieval buys recall by returning more:

| | Deterministic | Semantic |
| --- | ---: | ---: |
| Evidence items over the corpus | 132 | 212 |
| Exact evidence rate | 0.0752 | 0.0563 |
| Containing evidence rate | 0.1278 | 0.1080 |

The channel contributes its full candidate budget whether or not any candidate
is relevant, so precision falls as recall rises. Both numbers belong in any
claim made from this baseline.

## Against the Section 19.3 target

Primary evidence Recall@10 target is **≥ 0.90**. Measured: **0.6667** with the
semantic layer, **0.6000** without. **The target is missed on both sides.**

Two things this does not mean. It is not a regression — no earlier phase
measured conceptual retrieval at all. And it is not evidence that the semantic
layer is broken: it moved the number in the right direction on every recall
metric, and reached perfect abstention correctness, without a single
unsupported claim.

## Admission decision

Recorded, not taken. Gate authority for Phase 7 is the user, and the phase plan
admits an optional feature **only on measured uplift**. The measurement:

- uplift is **positive and real** on recall (+0.0667), abstention correctness
  (+0.0714), and exact symbol resolution (+0.0714);
- uplift is **modest** relative to its cost — a 61% increase in evidence
  volume for 6.7 points of recall;
- the Section 19.3 recall target is **missed** either way.

The honest summary is that the semantic channel helps, by less than the bug fix
it was blocked behind, and not enough on its own to reach the declared target.
