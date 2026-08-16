# ADR-0052: A claim beyond the first hop may not assert a direct relationship

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (ruling given 2026-08-17) and implementing agent
- Supersedes: none
- Related: ADR-0016 (derivation-tiered test edges; the mediation wording),
  ADR-0019 (export evidence labelling), ADR-0020 (relations in every graph
  answer), ADR-0051 (q006), `AGENTS.md` §4.1

## Context

Found while investigating **Task 6 (ranking sensitivity of the symbol corpus)**,
which is not what it was looking for. Ranking sensitivity turned out to require
a *distractor* — a returned symbol outside `expected_symbols` — and the only
source of distractors in symbol intents is second-hop traversal. Reading the
three cases that had them is what exposed this.

`BoundedGraphTraversal` runs to `TraversalLimits.max_depth = 2`, documented as
"the product's normal answer size". So a graph answer routinely contains edges
that touch **neither end of the root**. `_claims` did not account for that. Its
own comment states the premise that fails:

> The "other party" is whichever end of the edge is not the root.

At depth 2 neither end is the root, and the code nonetheless rendered the edge
against the root's name. Asking who calls `IdempotencyStore.claim` produced:

```
CLAIM : test_capture_uses_idempotency_store calls IdempotencyStore.claim
        at tests/test_service.py:5
CITES : tests/test_service.py:5 -> assert service.capture("order-1") == ...
PATH  : PaymentService.capture CALLS claim
      | test_capture_uses_idempotency_store CALLS PaymentService.capture
```

**The test does not call `claim`.** It calls `capture`. The claim asserts a
direct call that does not exist, and its own citation shows a *different* call.
`AGENTS.md` §4.1 requires evidence to support the claim; this does not.

**The structured data was correct throughout.** `relation_paths` carried the
real two-step path, with the second step naming `PaymentService.capture`
explicitly. Only the prose collapsed two hops into one. That is what makes this
a wording fix rather than a contract change.

## This is an engine defect

Stated plainly because the standing prior in `documentation/extra_build.md` —
*the instrument is wrong, not the engine* — had just held for the ninth
consecutive time in ADR-0051, and a prior confirmed nine times is exactly the
one that waves the tenth finding past.

It is **not the first** engine defect in this project's evaluation work.
ADR-0019 (export evidence labelling) was one, and its shape is nearly identical:
*the evidence named one symbol and showed another*. Here the **claim** names one
symbol and its evidence shows another. The same class of defect has now appeared
on two different surfaces.

## Decision

**A claim rendered from an edge that is not incident to the query root must not
assert a direct relationship. It names the symbol it went through.**

`claim_text` gains `intermediate: str | None`. `None` — the common case, an edge
touching the root — keeps the existing wording untouched. Otherwise:

```
{subject} reaches {object} indirectly, through {intermediate}, at {file}:{line}.
```

The wording deliberately mirrors ADR-0016's mediation branch (*"may exercise X
indirectly, through a fixture"*), which exists to solve the identical problem
one dimension over: that branch handles an edge whose *derivation* cannot
support the claim, this one an edge whose *distance* cannot. Both keep the edge
and change the sentence, and for the same reason ADR-0016 gave — filtering the
edge out would return "no callers" for a symbol several things genuinely reach,
and the caller could not tell "none exist" from "none direct".

`intermediate` is the edge endpoint that is not the far party: the **target**
for an inbound question, the **source** for an outbound one. Detection is local
and needs no path plumbing — an edge is direct exactly when the root is one of
its two endpoints.

### Deliberately unchanged

- **`derivation` and `confidence`.** A second-hop edge keeps the values it
  carries. Whether distance should lower a derivation is a separate decision
  with a much wider blast radius, and this record does not take it.
- **The contract.** No field added or removed; `contract_version` stays `1.1`.
  `relation_paths` was already correct and is untouched.
- **Which edges are returned.** Traversal, depth, and the answer set are
  unchanged. This record changes only what a sentence says.

## Consequences

- **Prose only.** Every tracked evaluation baseline is expected to reproduce
  unchanged, because no metric reads claim wording — `forbidden_claims` matches
  on declared phrases, and none of them describe a second hop. That is a
  limitation as much as a reassurance: **the corpus cannot see this fix**, the
  same blind spot recorded for ADR-0016's `claim_text` change.
- **The web, CLI, REST and MCP surfaces all improve together**, because they
  share the one application service. The opposite of the `--format pr` defect,
  where each adapter held its own copy.

### The mutation story, which is the reusable part

The fix was written test-first and the first tests were **worthless**, in a way
worth recording because it is not the usual failure.

Two mutations of the detection — never detect an intermediate, and hedge every
claim — **both passed the entire unit, integration and contract suite**. The new
`test_claim_text.py` cases could not catch either, because they pass
`intermediate` in by hand and therefore never exercise the code that computes
it. The fix and its test sat in different places with nothing covering the join:
the `--format pr` shape exactly.

An engine-level test in `tests/integration/test_graph_queries.py` was added for
both directions, and then a **third** mutation — computing the intermediate from
the wrong endpoint — exposed a flaw in that new test. It asserted `"total" in`
the *concatenation* of all claims, which the unrelated first-hop claim
("src.client imports total") satisfied on its own. Tightened to assert against
the single claim naming `Order`, all three mutations are caught.

**Assert against the one claim under test, never the joined text.** A
concatenation is satisfied by any claim in the answer, so the assertion passes
for a reason that has nothing to do with the behaviour being pinned.
