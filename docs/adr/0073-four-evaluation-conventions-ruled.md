# ADR-0073: Four evaluation conventions, ruled

- Status: accepted
- Date: 2026-09-01
- Decision owners: **user/product (all four rulings are the user's)** and
  implementing agent (framed the options and records the consequences)
- Related: ADR-0018 (graph expectations declare their subject), ADR-0051
  (raised `TRACE_FLOW` and declined to settle it), ADR-0057 (found the vacuous
  denominator), ADR-0059 (a graph expectation declares direct results)
- Supersedes: nothing. **Extends ADR-0059** on transitive results.

## Context

Four rows in the Deferred Register had been open on a ruling rather than on
work, some since 2026-08-16. DR-01 framed each with its evidence and options;
this records what was ruled and what each ruling costs. **A fifth — what
invalidates a stored parse — was withdrawn rather than put to the user**, because
ADR-0063 and ADR-0064 leave the change it authorises paying nothing.

## Ruling 1 — a caller expectation may name its own subject, and the cost is accepted

**Ruled: leave q005 and q053 as declared.**

q005 expects `IdempotencyStore.claim` among the callers of
`IdempotencyStore.claim`; q053 expects `OrderPipeline.advance` among its own.
Nothing calls itself in either fixture.

**The cost, stated plainly:** both cases permanently score below what the engine
actually achieves, and `relation_path_recall` understates the engine by that
margin for as long as they stand. This is a *declared* limit, not a defect — the
alternative rulings were to correct the cases or to change the engine, and
neither was chosen.

**No code or corpus changes.** The row closes as ruled, not as fixed.

## Ruling 2 — a case declaring no relations leaves the relation-precision denominator

**Ruled: exclude such cases from the metric.**

ADR-0057 found that a lexical answer can broaden with no metric moving, because
a case asserting no relations contributes a vacuous denominator that cannot
register a wrong relation.

**Consequence, which is the part to watch:** relation precision is computed over
a **smaller denominator**, so **the reported number will move**, and the tracked
Phase 3 and Phase 4 baselines are compared byte-for-byte by the gate. The
implementing task must regenerate the affected baseline **as its own reviewed
commit** — the precedent is `baseline-phase-7.json` on 2026-08-16 — and must
state the before and after side by side. **A metric that moves because its
denominator changed is not an improvement**, and must not be reported as one.

## Ruling 3 — traversal depth becomes part of each case

**Ruled: each case states its own traversal depth**, rather than depth-1 being
implied for every graph expectation.

This **extends ADR-0059** rather than overturning it: ADR-0059 ruled that an
expectation declares direct results, and left what to do about depth-2 open. It
is why q003, q005 and q015 are ranking-sensitive — their expectations omit
depth-2 results the engine returns, which then read as distractors.

**Consequence:** this is a **dataset contract change**, not a case edit. The
evaluation dataset contract is at 1.0 and gains a field, the loader and its
strict models change, and every graph case must declare a depth. The most
flexible option was chosen and it is also the most corpus churn — that is the
trade the ruling made.

## Ruling 4 — `TRACE_FLOW` is audited before it is ruled

**Ruled: audit all six cases, defer the ruling.**

ADR-0051 raised that the label may be systemically wrong and deliberately
declined to settle it with a single case in hand. That reasoning is upheld here:
the audit may find a **corpus limit or an engine defect**, and those have
opposite remedies. Ruling first would decide the question the audit exists to
answer.

**The row stays open**, with its trigger changed from "someone rules" to "the
audit runs".

## What this authorises

| Task | From | Character |
| --- | --- | --- |
| DR-07 | Ruling 2 | Metric change **plus a baseline regeneration as its own commit** |
| DR-08 | Ruling 3 | Dataset contract change, loader, and every graph case |
| DR-09 | Ruling 4 | An audit whose outcome is evidence, not a fix |

Ruling 1 authorises nothing and closes its row.

## Consequences

- No product behaviour changes and no version moves in this record. Every
  version bump belongs to the task the ruling authorises.
- **Two of the three tasks change a reported number.** Both must show the figure
  before and after and say which mechanism moved it, so a denominator change is
  never read as an engine improvement — the failure ADR-0053 recorded when a
  gated intent left the denominator and flattered six metrics at once.
