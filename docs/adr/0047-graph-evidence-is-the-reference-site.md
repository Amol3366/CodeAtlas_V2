# ADR-0047: Graph evidence is the reference site, not the definition range

- Status: accepted
- Date: 2026-08-16
- Decision owners: user/product (ruling given 2026-08-16) and implementing agent
- Supersedes: none
- Related: ADR-0020 (relations in every graph answer), ADR-0019 (export evidence
  labelling), ADR-0003 (evidence granularity), ADR-0027 (containment recall)

## Context

`containing_evidence_recall_at_10` sat at 0.8824 against a 0.90 target. A
per-case run (2026-08-15) found the shortfall is **exactly ten of 85 cases
scoring 0.00** while the other 75 score 1.00, from two unrelated causes. This
record settles the larger of the two: **eight cases** — q003, q006, q007, q013,
q016, q017, q026, q032.

In all eight, the corpus declares the **whole definition range** of the symbol
the answer is about, while the engine cites a **precise line inside it**:

| Case | Intent | Declared | Engine cites |
| --- | --- | --- | --- |
| q003 | `TRACE_FLOW` | `service.py:7-10` | `9-9`, `10-10` |
| q006 | `TRACE_FLOW` | `idempotency.py:5-9` | `8-8` |
| q007 | `RELATED_TESTS` | `test_service.py:3-5` | `5-5` |
| q013 | `DEPENDENCIES` | `orders.ts:5-6` | `5-5` |
| q016 | `CALLERS` | `client.js:3-4` | `4-4` |
| q017 | `EXPORTS` | `orders.ts:1-7` | `1-3`, `5-7` |
| q026 | `TRACE_FLOW` | `frontend.ts:1-4` | `2-2`, `3-3` |
| q032 | `TRACE_FLOW` | `frontend.ts:1-4`, `backend.py:1-2` | `2-2`, `3-3` |

`_contains` is directional: the predicted range must fully cover the expected
one. A narrow citation therefore cannot satisfy a wide expectation, and these
eight score zero.

## This is an absent decision, not a faulty instrument

**The distinction matters and this record is explicit about it**, because the
neighbouring finding (the `target/` ignore collision, ADR-0049) *is* a faulty
instrument and the two need different fixes.

Nothing here was broken. The engine has consistently cited reference sites. The
corpus has consistently — in these eight — declared definition ranges. Both were
internally coherent. **What never existed was a ruling on what evidence a graph
answer should cite.** The metric merely made the absence visible.

**The parallel with ADR-0031 is imperfect and is deliberately not leaned on.**
ADR-0031 corrected expectations naming a symbol the engine *could not produce*;
the expectation was unanswerable. Here the engine *could* emit a definition
range for a graph answer and chooses not to. That is a product decision that had
never been taken, not an instrument reporting a false result.

**The argument from majority is explicitly rejected.** It is true that q005 and
q015 — same intents, same era — declare reference sites and score 1.00, as do
the 23 graph cases added 2026-08-15. That is not why the reference site is
correct. A convention is not right because more cases follow it, and if the
count had gone the other way the reasoning below would be unchanged.

## Decision

**For a graph intent, the evidence is the reference site: the line that proves
the claim.**

The reasoning is the evidence contract. A graph answer's claim has the form
"X calls Y", "T tests M", "M exports S". What *proves* such a claim is the
site where the relationship is written — the call site, the test's invocation,
the export. `AGENTS.md` §4.1 requires evidence to **support** the claim; a
definition range cites more than the claim needs, offering the whole of Y when
the assertion is only that X reaches it.

ADR-0020 already leans this way: it requires every graph answer to populate
`relation_paths` with every supporting edge, and **an edge's evidence is a
reference site by nature** — an edge exists at a location, and that location is
where it is written.

Two consequences follow, and both are recorded rather than left implicit:

- **`_contains` is correct and is not loosened.** Its directionality and its
  docstring — "a citation that omits part of the answer has not proven it" —
  stand unchanged. The eight expectations are corrected; the comparator is
  untouched. Loosening it to accept overlap would move the number without
  settling anything, which is the move ADR-0003 exists to prevent.
- **`EXPORTS` keeps ADR-0019's rule.** There the reference site *is* the
  exported symbol's own definition, because that is what the export names. q017
  is therefore corrected to the two exported symbols' ranges, not to a single
  line.

## Consequences

- Eight expectations corrected. `_contains`, the engine, and the metric
  definitions are untouched — this is a corpus correction under an explicit
  ruling, not a threshold change.
- The corpus stops holding two conventions for the same question shape, which no
  aggregate could have surfaced: cases following each convention sat in the same
  average.
- **This moves a number**, and the justification is the ruling above rather than
  the movement. The measured effect and any case that does *not* reach 1.00 are
  recorded in the 2026-08-16 handoff, per case, including where the engine's
  citation and the corrected expectation still disagree.
- Future graph cases declare reference sites. The ADR-0036 validator does not
  enforce this and is not extended to; whether a resolvable range is the *right*
  range is what the metrics are for.
