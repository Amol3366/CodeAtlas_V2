# ADR-0030: s001 is a granularity disagreement, and the engine is not changed

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: ADR-0003 (evidence granularity), ADR-0027 (containment recall),
  ADR-0028 (rank fusion, and its recorded coarse-chunk limitation)

## Context

s001 — *"How do we stop two shoppers buying the last one of something?"* —
declares `InventoryLedger.reserve` at `src/orders/inventory.py:20-28`. After
ADR-0027, ADR-0028 and ADR-0029 it is the last conceptual case whose expected
**symbol** is outside the top 10, and it was carried as the final open item.

Investigating it produced no defect. The relaxed lexical query is:

```text
"stop" OR "two" OR "shoppers" OR "buying" OR "last" OR "one" OR "something"
```

- The **module** chunk `src.orders.inventory` matches on `two`, because its
  docstring is *"Keeping two customers from being sold the same unit."*
- `InventoryLedger.reserve` matches **nothing**. Its docstring is *"Hold units
  for an order that has not shipped yet… a negative reservation is a promise
  the warehouse cannot keep."*

The lexical channel is therefore correct to omit the method: it contains no
query term. The semantic channel ranks it 12th. Both channels rank the module
**first**, and they are right to — *"How do we stop two shoppers buying the last
one of something?"* against *"Keeping two customers from being sold the same
unit"* is close to a paraphrase.

**The engine returns the chunk that best answers the question as asked. The
corpus declares the method that implements it.** That is a disagreement about
granularity, not an accuracy failure.

## Decision

**Change nothing.** Record the finding, and leave the corpus unedited.

Three reasons, in order of weight.

**1. The two metrics pull in opposite directions here.**

| Metric | s001 today |
| --- | --- |
| `containing_evidence_recall_at_10` | **satisfied at rank 1** — the module chunk `1-36` contains the expected `20-28` |
| `symbol_recall_at_10` | missed — the method is 12th by name |

The obvious lever is a granularity penalty so a whole-module chunk cannot
outrank a specific symbol — the coarse-chunk bias ADR-0028 recorded as untuned
and predicted would resurface. Applied here it would **demote the very chunk
providing the rank-1 containment hit**. Fixing the symbol number risks the
evidence number, which is the ADR-0018 and ADR-0025 trade appearing in ranking
policy rather than in extraction. A change with that shape needs to be measured
across the corpus, not fitted to one case.

**2. Editing the corpus is forbidden and would be the easy answer.** Declaring
`src.orders.inventory` an acceptable answer would close s001 immediately and is
exactly what ADR-0003 refuses: the corpus is not adjusted to match engine
behaviour.

**3. Nothing is failing.** `symbol_recall_at_10` is 0.9286 against a 0.90
target and Phase 7's conceptual corpus reports `targets_met: true`. s001 is
discretionary polish. Spending ranking risk on a case that fails no gate is a
poor trade.

## The open ruling this leaves

**When a question is conceptual and the concept is documented at module level,
does the module satisfy it?**

If yes, s001's expectation is under-specified rather than missed, and the
corpus should say so — as a declared expectation, not as an edit made to move a
number. If no, the engine needs to prefer implementing symbols over documenting
containers for conceptual intent, and that is a ranking change requiring
corpus-wide measurement and its own record.

This is the same shape as the open q019 ruling, where the corpus writes
`README.Health` and extraction emits a bare `Health`. Both are the corpus and
the engine disagreeing about which name or level answers a question, and neither
is resolvable by looking at one case.

## Alternatives

**Penalise coarse chunks so leaves outrank containers.** Deferred, not
rejected — but it must be justified by corpus-wide measurement, because the
measurable effect here is to trade an evidence hit for a symbol hit. ADR-0028
already declined to add this knob without its own evidence; s001 is one case,
not that evidence.

**Add query expansion so "shoppers" reaches "customers".** A synonym layer is a
large, separately-measured feature, and it would change every lexical result in
the product to close one conceptual case.

**Declare the module an accepted answer in the corpus.** Rejected: ADR-0003.

## Consequences

- s001 stays as the single `symbol_recall_at_10` miss, at 0.9286 against 0.90,
  and Phase 7 remains fully met.
- ADR-0028's coarse-chunk limitation now has a concrete case attached, which is
  useful to whoever eventually measures it — including the warning that a naive
  penalty regresses containment on this case.
- No source, corpus, contract, schema, or baseline file changes. Every metric is
  unchanged, because nothing was changed.

## Security and Privacy

None. No code, data movement, or configuration changed.

## Migration and Rollback

Not applicable. Nothing to migrate; reverting this record removes a document.

## Approval

Approved by the user on 2026-08-10, who asked for the finding to be written up
rather than for the ranker to be changed after the metric tension was reported.
