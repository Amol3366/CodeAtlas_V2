# ADR-0055: A route cites the handler it reaches

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (ruling given 2026-08-17) and implementing agent
- Supersedes: none
- Related: ADR-0034 (a flow follows routes), ADR-0047 (graph evidence is the
  reference site), ADR-0019 (export evidence labelling), ADR-0052 (a claim may
  not outrun its citation), ADR-0020

## Context

`extra_build.md` Task 5, and the last open row from ADR-0034's decomposition:

> q032 traces frontend → backend. After ADR-0047 the frontend hop matches;
> `backend.py:1-2` — the endpoint the flow actually reaches — is **never
> cited**, so the case caps at **0.50**. Either a trace answer should carry
> evidence at its far end, or a two-hop expectation should not declare one.

The tension is real. ADR-0034 added `ROUTES_TO` to `trace` because "a flow
question is the one question that most needs to cross [the HTTP boundary]".
ADR-0047 then ruled that a graph answer's evidence is the **reference site** —
which for a route is the literal in the caller's file, not the handler.

Under that general rule q032's second expectation is wrong. Under ADR-0034's
purpose, citing only the near side answers half the question asked.

## A defect found while reproducing it

Probing `trace(loadOrder)` showed three edges and **two** claims:

```
loadOrder CALLS     fetch      line=2  unresolved   -> claim kept
loadOrder ROUTES_TO get_order  line=2  RESOLVED     -> claim DROPPED
loadOrder CALLS     json       line=3  unresolved   -> claim kept
```

Evidence is deduplicated by region — correctly, and for a stated reason: "two
candidates covering the same lines of the same file are one piece of evidence,
not two." But `_claims` was built from the *surviving pairs*, so the second edge
sharing a line lost its claim entirely. **The engine dropped its only resolved,
cross-language edge and kept two unresolved browser globals, decided purely by
iteration order.** `relation_paths` carried the route; the prose did not — the
ADR-0020 gap inverted.

The two problems are coupled: a route that cites its own destination no longer
shares a region with the call beside it, so the citation ruling fixes the
dropped claim as a consequence rather than as a separate patch.

## Decision

**A resolved `ROUTES_TO` edge additionally cites the handler's definition,
labelled with the handler.** Ruled by the user.

This is an **explicit exception** to ADR-0047, recorded as one rather than
smuggled in as an interpretation. Its precedent is ADR-0019's `EXPORTS` carve-
out, which ADR-0047 preserved: there "the reference site *is* the exported
symbol's own definition, because that is what the export names". A route names
its handler the same way — and unlike an export, its literal and its target sit
in different files and usually different languages, so the near side alone
cannot show what the flow reaches.

**Unresolved routes cite nothing extra.** A route to a handler nothing resolved
has no definition to cite, and inventing one is the failure this product exists
to refuse.

**Two citations, one claim.** The literal and the handler support the same
assertion, so `_claims` merges per edge rather than emitting it twice.

`_verb` gained `ROUTES_TO: "routes to"`. It had no entry, so the claim would
have read "loadOrder **relates to** get_order" — the generic fallback, on the one
relation whose whole point is the boundary it crosses. Nobody had seen it
because the route's claim was being dropped.

## Consequences

| Metric | Before | After |
| --- | ---: | ---: |
| `containing_evidence_recall_at_10` | 0.9943 | **1.0000** |
| `primary_evidence_recall_at_10` | 0.9310 | 0.9368 |
| `symbol_recall_at_10` | 0.8833 | 0.8917 |
| `ndcg_at_10` | 0.9109 | 0.9173 |
| `containing_evidence_rate` | 0.7576 | 0.7537 |

q032 reaches **1.00**, and `containing_evidence_recall_at_10` reaches 1.0000 —
every case in the corpus now scores. `containing_evidence_rate` falls, expected
and ungated (ADR-0048): an answer that cites more is measured against more.
`unmet_targets` stays `['changed_symbol_precision']`. `baseline-phase-7` and
`rerank-phase-7` reproduce byte-for-byte.

**This settles the last of ADR-0034's four causes for `trace`.** The lexical
half (q024, q027, q029) is Task 4 and remains open on its own ruling.

### What the tests do and do not cover

Four mutations were run. Two were caught immediately; **two were not, and both
for the same reason — the fixture cannot exercise them.** That is recorded here
rather than left as apparent coverage.

- **Over-applying the carve-out to every relation kind was not detected.** Every
  non-route edge in `mixed_app` targets a browser global and resolves to
  nothing, so the mutation is a no-op there and the guard was green while
  proving nothing. Replaced with a `python_app` test over
  `PaymentService.capture`, whose `CALLS` *is* resolved — the case that would
  gain a second citation if the carve-out leaked. That mutation now fails.
- **Deleting the per-edge claim merge was not detected, and still is not.** A
  route literal and the call carrying it are the same expression, so they share
  a line; the route's near-side candidate is deduplicated away and only one
  citation survives, so the merge never fires in this fixture. It is **not dead
  code** — it fires whenever the near side survives, which needs a fixture whose
  route literal sits alone on its line. Kept, and recorded in the Deferred
  Register as a stated limit of what the suite measures rather than as coverage
  it has.

**A mutation that cannot apply is indistinguishable from a test that cannot
catch it.** Both of these looked like passing guards.
