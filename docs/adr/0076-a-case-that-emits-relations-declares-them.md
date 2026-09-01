# ADR-0076: A case that emits relations declares them

- Status: accepted
- Date: 2026-09-02
- Decision owners: **user/product** (chose this option over the two others) and
  implementing agent (found the ruling's premise false and re-put the question)
- Related: ADR-0057 (a lexical answer carries its resolved edges — raised this),
  ADR-0038 (relation recall added because precision punished compliance),
  ADR-0036 (expectations name real symbols), ADR-0003 (the corpus is not edited
  to move a number), ADR-0053 (a denominator change is not an improvement)
- Implements: ADR-0073 ruling 2, **after correcting its premise.**

## Context

ADR-0057 recorded that **a lexical answer can broaden with no metric moving.**
q006 and q031 emit true relation edges the corpus does not declare, so their
per-case precision falls from 1.00 to 0.00 — and the aggregate cannot see it.

ADR-0073 ruling 2 ruled "exclude such cases from the metric", and predicted the
denominator would shrink and the reported number would move.

## The premise was already false, and the options were inverted

`runner.py` builds `relation_scores` under `if case.expected_relations and
score.measured`. **Cases declaring no relations have been excluded since before
the ruling.** Excluding them is the status quo, so that reading is a no-op and
nothing could move.

Worse, the two options in the brief carry each other's consequences.
`_precision(predicted, ∅)` returns **0.0** when anything is predicted, so
*keeping* a vacuous case is what would make broadening visible; **excluding is
what keeps it invisible** — the very complaint the row was opened on.

Rather than pick a reading, the question was put again with that evidence. The
answer chosen was the third option, which the original brief had listed and
described as corpus work rather than a metric change.

## Decision

**A case whose answer carries relations declares them.** Nothing is vacuous, so
the existing exclusion stops hiding anything: a case that broadens now has a
declaration to be measured against.

Three cases emit relations while declaring none, and all three now declare:

| Case | Intent | Declared |
| --- | --- | --- |
| q003 | `TRACE_FLOW` | `PaymentService.capture CALLS IdempotencyStore.claim` |
| q006 | `CONCEPTUAL` | the two `IdempotencyStore CONTAINS …` edges |
| q031 | `DOCUMENT_LOOKUP` | `Order flow DOCUMENTS get_order` / `… loadOrder` |

**The gold was read off the fixture source, not transcribed from the engine.**
That distinction is the whole of ADR-0003, and ADR-0036 records two occasions
where an expectation named something the engine could not produce because nobody
had checked the source. Specifically:

- **q003** — `service.py:10` calls `self.store.claim(key)`, and `store` is
  annotated `IdempotencyStore` on `__init__`, so the target resolves.
- **q006** — `idempotency.py` defines exactly `__init__` and `claim` inside the
  class. **Both** edges are declared: declaring only the answer-bearing one
  would penalise the engine for citing every supporting edge, which is precisely
  the defect ADR-0038 had to correct by adding recall beside precision.
- **q031** — `flow.md:3` describes the frontend requesting the route `loadOrder`
  calls; `flow.md:5` describes what `get_order` returns. The derivation
  discriminates rather than matching prose by coincidence: it emits **no** edge
  to `health`, which the document never mentions. ADR-0057 had already dropped
  the eight unresolved prose-word edges.

That the engine then agrees with all seven declared edges is a **result, not the
method**.

## Consequences

- **`relation_path_correctness` moves 0.8932 → 0.9024**, and it moves because
  the denominator grew from 24 to 27 measured cases, each scoring 1.0. **This is
  not the engine getting better** — no engine code changed and no answer
  changed. ADR-0053 records what happens when a denominator change is read as an
  improvement; this record exists partly so this one cannot be.
- **`relation_path_recall` stays 1.0**, so ADR-0058's absolute gate holds. That
  is also the strongest check on the gold: seven edges declared from source, and
  every one of them emitted.
- **Exactly one line changes in each of `baseline-phase-3.json` and
  `baseline-phase-4.json`.** Everything else is byte-identical, including Phase
  3's four pre-existing unmet targets. Regenerated as its own reviewed commit,
  the precedent being `baseline-phase-7.json` on 2026-08-16.
- **The hole cannot reopen.** `test_no_measured_case_emits_relations_it_does_not_declare`
  is derived from the corpus rather than listing the three cases fixed, so a new
  lexical or conceptual case that emits relations without declaring them fails.
  Mutation-checked by stripping q031's declarations.
- No schema, no contract version, no engine change.

## What this does not do

It does not make relation accuracy measurable for cases that emit **nothing** —
those still contribute no denominator, correctly, because there is nothing to be
right or wrong about. And it measures only the corpus's own fixtures: ADR-0056
already records that the corpus reaching fusion is 14 cases over one fixture, and
this record does not widen that.
