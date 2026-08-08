# ADR-0019: Evidence Is Labelled With the Symbol Its Lines Show

- Status: accepted
- Date: 2026-08-08
- Decision owners: user (approved taking the module-symbol finding as the next slice), implementing agent (record)
- Supersedes: none
- Extends: ADR-0004 (relation model), ADR-0016 (a claim may not outrun its evidence)

## Context

ADR-0018 deferred a finding it described as "module-scoped graph queries rank
the module's own symbol first". Investigating it showed that framing was
imprecise: the finding decomposes into two unrelated things, and only one is an
engine defect.

`GraphQueryService._respond` labelled every evidence item with the edge's
**source** symbol. Checking each label against the range it cites:

| Query | Cited range | Range actually contains | Label was |
| --- | --- | --- | --- |
| `exports(src.orders)` | `orders.ts:1-3` | `Order`'s definition | `src.orders` ✗ |
| `exports(src.orders)` | `orders.ts:5-7` | `total`'s definition | `src.orders` ✗ |
| `dependencies(src.payments.service)` | `service.py:1` | the import statement, at module scope | `src.payments.service` ✓ |
| `callers(total)` | the call site inside `render` | `render`'s body | `render` ✓ |

Almost every relation kind cites a **reference site** — a call, an import, a
name use — and that line sits inside the source symbol, so the source label is
correct. `EXPORTS` is the exception: it cites the **exported symbol's own
definition**. `export interface Order {` is `Order`'s range, not the module's.

So an `EXPORTS` evidence object named one symbol and showed another. That is
precisely the defect ADR-0016 named on the `related_tests` surface — a reader
told a fact and shown evidence that cannot support it — and the product's whole
claim is that what a reader is shown can be verified.

The existing integration tests asserted **claim text only** and never an
evidence label, which is why this survived since Phase 3. The claims were always
right: `_claims` already resolves the "other party" by direction (source when
inbound, target when outbound), so `src.orders exports Order` read correctly
while the evidence beside it was mislabelled.

## Decision

**Label evidence with the symbol whose definition the cited range covers.**
Implemented as `_cited_symbol`: `EXPORTS` takes the edge's target, every other
kind keeps the source.

The rule is deliberately expressed as "what do these lines show" rather than
"which end of the edge is the answer". Those two coincide for `EXPORTS` but are
different questions, and the second one is already answered — by the claim.

**The counterpart is pinned by its own test.** An `IMPORTS` range is the import
statement, which lives in the importing module, so that label must *not* flip
along with `EXPORTS`. A single test asserting only the new behaviour would have
permitted a change that fixed exports by breaking imports.

## Consequences

`exact_symbol_resolution` 0.6667 → 0.6923 (q017). **No other metric moved** —
evidence counts, recall, and the three evidence rates are all unchanged, which
is the correct signature for a pure relabel: the same evidence, named properly.
Change-side metrics are untouched, so the Phase 4 gate approval stands.

The label is contract-visible, so it reaches CLI, REST, MCP, and the web app
identically — all four route through this one application service. A citation in
the evidence panel for an export now names the exported symbol.

The target remains unmet: **0.6923 against 0.98.**

### The other half of the deferred finding is not an engine issue

For an **outgoing** query the answer lives in the claim, not in the evidence
label, because the evidence cites the reference site inside the subject. So
`dependencies(src.payments.service)` correctly labels its evidence
`src.payments.service` and correctly claims `imports IdempotencyStore`.

The evaluation harness projects `ranked_symbols` from evidence labels
(`[item.symbol for item in response.evidence]`). That projection is right for
inbound queries, where the label *is* the answer, and wrong for outbound ones,
where it names the subject. q010 and q015 still score as misses for this reason
alone.

That is a harness question, not a product one, and it is left open rather than
folded in here — the fourth consecutive finding to land on the measuring
apparatus rather than the engine
(`exact_symbol_resolution`, `valid_evidence_rate`, ADR-0018's subject
confusion, and now this).

**A note on how this was found.** ADR-0018 recorded the symptom — "returns
`src.client` at rank 1" — as though it were the diagnosis. The actual defect was
narrower than the symptom suggested and sat in a different place than the label
"ranking" implied. Reading each evidence item against the source lines it cites
is what separated the two; the run output alone could not.
