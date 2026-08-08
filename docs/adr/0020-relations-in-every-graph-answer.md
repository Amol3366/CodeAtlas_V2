# ADR-0020: Every Graph Answer Carries Its Relations Structurally

- Status: accepted
- Date: 2026-08-08
- Decision owners: user (approved the product change over a harness-only fix), implementing agent (record)
- Supersedes: none
- Extends: ADR-0004 (relation model and additive contract growth)

## Context

ADR-0019 closed half of a deferred finding and left the other half described as
"the evaluation harness projects `ranked_symbols` from evidence labels, which is
right for inbound queries and wrong for outbound ones". Investigating how to fix
that projection showed it could not be fixed in the harness at all, and that the
reason was a product gap.

**The answer to an outbound relation question existed only as English.** `Claim`
carries `claim_id`, `text`, `derivation`, `confidence`, `evidence_ids` — no
structured subject or object. Evidence cites a reference site, so its label
names the symbol containing that line: the caller for "who calls this" (the
answer), the importer for "what does this import" (the subject). For an outbound
query there was therefore nowhere in the response to read the answer from except
the prose.

The PRD names "a coding agent working in the repository, connects over MCP,
needs facts it can act on rather than plausible prose" as one of three target
users. Asking CodeAtlas over MCP who calls a symbol returned evidence labelled
by containing symbol plus a sentence, and nothing machine-readable in between.

`RelationStep` already exists for exactly this — `source`, `kind`, `target`,
`derivation`, `confidence`, `evidence_id`, one per edge, each independently
citable — and `relation_paths` has sat on `QueryResponse` since Phase 3 as an
additive optional field. It was populated only when `include_paths=True`, which
only `trace` passed.

**`BoundedGraphTraversal.expand` computes those paths for every graph query.**
`_respond` then discarded them for everything except `trace`. The data was
already there and was being thrown away.

A consequence nobody had noticed: `relation_path_correctness` has been
**0.0000 in every baseline since Phase 3** and is structurally incapable of
anything else. Ten of the twelve cases declaring `expected_relations` received
an empty list, and for the remaining two the harness rendered a path as
`" -> ".join(step.target …)` — targets only — while the corpus writes
`"render CALLS total"`. Those strings can never be equal. The metric also has no
entry in `_unmet_targets`, so nothing gated it. Six baselines carried a dead
number that twelve declared corpus expectations were feeding.

## Decision

**1. Populate `relation_paths` for every graph query.** `include_paths` is
removed rather than defaulted, because a flag whose only remaining value is
`True` is a decision nobody makes. Additive per ADR-0004: the field has always
existed, and a client that ignores it is unaffected. `contract_version` stays
`1.1`; no migration.

**2. The harness reads the answer from the step, not the evidence label.**
`GRAPH_ANSWER_END` names which end of a step answers which intent — `source` for
`CALLERS` and `RELATED_TESTS`, `target` for `DEPENDENCIES` and `EXPORTS`.

**3. `TRACE_FLOW` is deliberately excluded from that table.** A flow answer
*includes* its origin — the corpus expects `PaymentService.capture` back when
tracing from it — whereas a relation answer never does. Those are different
questions, and collapsing them would have traded two newly-correct cases for
several newly-broken ones.

**4. Relation predictions use the corpus's `SOURCE KIND TARGET` form**, one
string per step.

## Consequences

| Metric | Before | After |
| --- | ---: | ---: |
| `exact_symbol_resolution` | 0.6923 | 0.7436 |
| `mean_reciprocal_rank` | 0.7051 | 0.7436 |
| `relation_path_correctness` | 0.0000 | **0.2083** |
| `symbol_recall_at_10` | 0.6538 | 0.6667 |
| `ndcg_at_10` | 0.6625 | 0.6841 |
| everything else | unchanged | unchanged |

The product change **on its own moved no metric** — measured before the harness
changes were made — which is the honest way round: the response gained data the
evaluation could not previously read, and only then could the harness read it.

**`relation_path_correctness` is now capable of measuring, and measures 0.2083.**
That is not a good score and is not presented as one. The residual is largely a
naming-convention difference: the corpus writes `orders EXPORTS Order` and
`service IMPORTS idempotency` while the engine emits qualified names
(`src.orders`, `src.payments.service`, `IdempotencyStore`). **The corpus was not
edited to close that gap** (ADR-0003). Whether the corpus should use qualified
names, or the metric should compare unqualified suffixes, is a separate decision
that must be made explicitly rather than by quietly rewriting expectations.

The metric still has no gate target. Giving it one is a decision for the project
owner and is deliberately not taken here.

Target remains unmet: **0.7436 against 0.98.**

### Verification note

All three harness tests passed the moment they were written, because the
behaviour they describe was already implemented. Each was therefore
mutation-checked: forcing `GRAPH_ANSWER_END` lookups to `None` fails the
outbound test, adding `TRACE_FLOW` to the table fails the trace test, and
restoring the target-join fails the relation-form test. A test that has never
been observed failing is a comment.
