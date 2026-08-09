# ADR-0034: A flow follows routes, and says when it cannot build a path

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: ADR-0020 (relations in every graph answer), ADR-0004 (relation model)

## Context

`relation_path_correctness` measured 0.3182 with **no gate target**, and had
never been examined. Decomposing it across the eleven cases that feed it shows
why no threshold could have meant anything — it averages four unrelated causes:

| Cause | Cases |
| --- | --- |
| A flow answer emits no path at all | q026, q032 |
| Lexical intents emit no relation paths | q027, q029 |
| Module naming convention (`orders` vs `src.orders`) | q010, q015, q017 |
| Precision penalises a second, true edge | q005 |
| Passing | q007, q013, q016 |

**This record fixes only the first.** The rest are decisions, recorded below.

Two defects sit behind q026 and q032, and neither is a retrieval failure — the
expected edge `loadOrder ROUTES_TO get_order` is extracted, resolved, and stored:

**1. `trace` never traversed `ROUTES_TO`.** Its kinds were `CALLS`, `MAY_CALL`
and `IMPORTS`. `ROUTES_TO` exists specifically to model an HTTP boundary
(P4-05), and a flow question is the one question that most needs to cross it.
Without it a trace stops at the frontend caller and never reaches the handler it
invokes — the cross-language capability the `mixed_app` fixture exists to
demonstrate.

**2. An answer with edges but no path said nothing.** `loadOrder` also calls
`fetch` and `json`, browser globals that resolve to nothing. A path needs
resolved endpoints, so none could be built. The response nonetheless reported
*"loadOrder has 2 flow"*, rendered two claims, cited two evidence items, and
returned an **empty `relation_paths` with no warning**. A client reading the
structured field saw nothing and was told nothing.

That second one is the same gap ADR-0020 set out to close — an MCP client
getting prose and evidence with nothing machine-readable between them — still
open for unresolved targets, and invisible because the empty list looked like a
legitimate "no relations".

## Decision

**Add `ROUTES_TO` to `trace`'s traversed kinds, and warn
`RELATION_PATH_UNRESOLVED` when edges were counted but some produced no path.**

The warning compares counts rather than identities, because `_paths` withholds
*all* of a path's steps when any one step loses its evidence — so an edge can
vanish without being individually identifiable at that point. Comparing
`len(result.edges)` against the total steps across paths detects the shortfall
without pretending to name which edge caused it.

It fires on a shortfall, not only on total absence. The summary counts **edges**
and `relation_paths` carries **paths**; when they disagree, the disagreement is
the thing worth reporting. `loadOrder` now returns three flow relations and one
path, and says so.

`NO_RELATIONS_FLOW` is untouched and still means something different — no edges
at all. Collapsing the two would lose the distinction between "nothing relates
to this" and "relations exist that cannot be expressed as a path", which is
precisely the distinction Section 4.1 asks for.

## Measured

| Metric | Before | After |
| --- | ---: | ---: |
| `relation_path_correctness` | 0.3182 | **0.5000** |

q026 and q032 move from 0.0000 to **1.0000**, emitting exactly the declared edge
and nothing extra.

**No other metric moved on any baseline**, and `baseline-phase-7` and
`rerank-phase-7` both still reproduce byte-for-byte. That is the correct
signature for adding one relation kind to one intent's traversal: it changes
what a flow question answers and nothing else.

## What this does not fix

Recorded so the remaining 0.5000 is not mistaken for engine weakness:

- **Lexical intents emit no relation paths** (q027, q029). `DOCUMENT_LOOKUP` and
  `CONFIG_LOOKUP` answer through `search_text`, which has no graph step — yet
  the edges they declare (`Order flow DOCUMENTS get_order`,
  `healthPath REFERENCES health`) are stored. Whether a lexical answer should
  carry stored relations is a design decision, not a defect to fix quietly.
- **Module naming** (q010, q015, q017). The corpus writes `orders EXPORTS
  Order`; the engine emits `src.orders EXPORTS Order`. The same class as the
  q019 ruling settled in ADR-0031, and unresolvable by looking at one case.
  q010 additionally disagrees about target granularity — the module
  `idempotency` versus the class `IdempotencyStore` actually imported.
- **Precision penalises truth** (q005). The engine emits two edges, *both
  correct*; the corpus declares one; precision scores 0.5. ADR-0020 deliberately
  made graph answers carry **every** supporting relation, so this metric
  penalises behaviour another record mandates. Precision may simply be the wrong
  instrument, exactly as exact-match was for evidence recall in ADR-0027.

**`relation_path_correctness` still has no gate target, and should not get one
until the above are settled.** A threshold over four unrelated causes cannot be
reasoned about — which is the same lesson ADR-0023 recorded when one target
table was applied to two different corpora.

## Alternatives

**Add every relation kind to `trace`.** Rejected: a flow is a directed
execution path, and `TESTS` or `DOCUMENTS` edges are not steps in one. ADR-0020
already established that `TRACE_FLOW` needs different handling from other graph
answers.

**Warn only when no path at all could be built.** The first implementation, and
it stopped firing the moment `ROUTES_TO` produced one path — leaving two
unrepresented edges silent again. A test caught it.

**Suppress the claims for unresolved targets instead of warning.** Rejected:
the claims are true and evidence-backed. The problem was never that they were
shown, only that the structured field disagreed without saying so.

## Security and Privacy

None. One additional relation kind traversed within the existing bounded
traversal limits, and one warning string.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`; the warning is additive per ADR-0004 and clients ignoring unknown
warnings are unaffected. Rollback is reverting the commit and regenerating
`baseline-phase-3` and `-4`.

## Approval

Approved by the user on 2026-08-10, who chose to fix the trace defect alone and
leave the other three causes as recorded decisions.
