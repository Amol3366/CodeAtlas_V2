# ADR-0046: A module-level answer satisfies a conceptual question

- Status: accepted
- Date: 2026-08-15
- Decision owners: user/product (ruling given 2026-08-15) and implementing agent
- Supersedes: none — it *resolves* the question ADR-0030 left open
- Related: ADR-0030 (s001 is a granularity disagreement), ADR-0028 (rank fusion
  and its recorded coarse-chunk limitation), ADR-0003 (evidence granularity),
  ADR-0023 (target profiles)

## Context

ADR-0030 investigated corpus case s001 — *"How do we stop two shoppers buying
the last one of something?"* — and found **no defect**:

- The **module** `src.orders.inventory` has the docstring *"Keeping two
  customers from being sold the same unit."* Both retrieval channels rank it
  first, and ADR-0030 concluded they are right to: the question is close to a
  paraphrase of that sentence.
- `InventoryLedger.reserve`, which the corpus declares, matches **no query
  term** at all.

The engine returns the chunk that best answers the question *as asked*; the
corpus declares the method that *implements* it.

ADR-0030 changed nothing, for a reason that still holds: the obvious lever — a
granularity penalty so a whole-module chunk cannot outrank a specific symbol —
would promote the method **and demote the very chunk providing the rank-1
containment hit**. It trades an evidence hit for a symbol hit. That ADR left the
underlying product question open and named it as needing an owner's ruling.

The question is not answerable from the code. It is: **when a concept is
documented at module level and the corpus declares the method implementing it,
is the module a correct answer?**

## Decision

**Yes. A module-level answer satisfies a conceptual question.**

The engine's behaviour is correct as it stands, and **no ranking change is
made**. Specifically:

- The coarse-chunk penalty contemplated in ADR-0028 and ADR-0030 is **not**
  implemented. The rank-1 containment hit that s001 currently produces is
  preserved.
- Where a conceptual case's expectation names only the implementing symbol and
  the engine answers with the module that documents it, **the expectation is
  the thing that is too narrow**, not the answer.

Correcting such an expectation is permitted only under the existing rule: it
must be justified as ADR-0031 and ADR-0036 require — the expectation named
something the engine cannot produce, or contradicted itself — and it must be
*widening* rather than replacement, so the implementing symbol remains an
accepted answer. **ADR-0003 still forbids editing the corpus to move a number**,
and this ruling is not a licence to do so.

## Why this rather than the alternative

**"No — the method is the answer"** would have authorised the coarse-chunk
penalty in WS-5, measured corpus-wide. It was rejected on three grounds.

1. **ADR-0030 already found no defect.** Ruling the other way would declare a
   defect where an investigation found none, which is the pattern this project
   has had to correct seven times (ADR-0017, 0018, 0024, 0027, 0038, the
   2026-08-13 document-section report, and both register rows corrected on
   2026-08-15).
2. **It spends real risk to move an ungated number.** `symbol_recall_at_10` is
   gated at 0.90 only on the *conceptual* target profile (ADR-0023); on the
   retrieval profile it is ungated, and nothing fails today.
3. **The trade is against the product's own priority.** Evidence is what
   CodeAtlas is for. Demoting the chunk that supplies a rank-1 evidence hit in
   order to raise a symbol-name metric inverts that.

## Consequences

- **No code changes.** This ADR records a decision, not an implementation.
- **WS-5 changes shape.** It is no longer "fix the RRF coarse-chunk bias" but
  "measure whether the bias costs anything now that the corpus is larger". The
  RRF coarse-chunk row in the Deferred Register is reframed accordingly, and its
  trigger — "the module-granularity ruling lands" — is now satisfied.
- **Conceptual cases may declare more than one acceptable answer.** Nothing
  requires a case to be widened; this ADR only settles that widening is
  legitimate where the module genuinely documents the concept.
- The `symbol_recall_at_10` figure on the conceptual corpus should be read with
  this ruling attached: a case counted as a miss because the module outranked
  the method is a **corpus expectation issue**, not an engine one.

## What this does not decide

It does not say a module is *always* an acceptable answer. It says a module that
documents the concept satisfies a question about that concept. A module returned
because it is merely large, or because it happens to contain the answer without
describing it, is not covered here and remains a ranking question.
