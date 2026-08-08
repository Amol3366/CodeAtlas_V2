# ADR-0018: A Graph Case Declares Its Subject

- Status: accepted
- Date: 2026-08-08
- Decision owners: user (approved the additive field and the deferral of the ranking question), implementing agent (record)
- Supersedes: none
- Extends: ADR-0003 (the corpus is not edited to improve a number)
- Corrects: ADR-0017 (see "The correction" below)

## Context

`_query_term` fed `expected_symbols[0]` to the engine as the thing being asked
about. For an exact or lexical case that is right: "Where is `Order` declared?"
is *about* `Order` and also expects `Order` back.

For a graph case it is wrong. `expected_symbols` is the **answer**; the subject
is not in it. "Who calls `total`?" expects `render` and is about `total`, so the
harness asked the engine who calls `render` — a different question — and then
scored the engine's correct answer to that different question as a miss.

The corpus had no field naming the subject, so the harness inferred it. The
inference happened to hold for six of the twelve graph cases, which is why the
defect looked like a language-specific capability gap rather than a convention
error.

Probing the graph service directly with the correct subject separates three
causes among the six failing cases:

| Case | Intent | Subject | Top-1 with correct subject | Cause |
| --- | --- | --- | --- | --- |
| q005 | `CALLERS` | `IdempotencyStore.claim` | `PaymentService.capture` ✓ | subject only |
| q016 | `CALLERS` | `total` | `render` ✓ | subject only |
| q007 | `RELATED_TESTS` | `PaymentService.capture` | *(no evidence)* | method/class resolution |
| q010 | `DEPENDENCIES` | `service` | `src.payments.service` | module-symbol ranking |
| q015 | `DEPENDENCIES` | `client` | `src.client` | module-symbol ranking |
| q017 | `EXPORTS` | `orders` | `src.orders` | module-symbol ranking |

## Decision

**1. `QueryCase` gains an optional `query_subject`.** Absent means
`expected_symbols[0]`, which is correct for every exact, lexical, and
self-referential case, so all 40 existing cases stay valid unchanged. The model
is `extra="forbid"`, so the corpus could not carry this until the model
declared it.

**2. Six cases declare it: q005, q007, q010, q015, q016, q017.** This is
additive — it records what each question is about. No expectation was
re-labelled, no case reworded, no symbol added to or removed from an expected
set. ADR-0003 holds.

**3. The subject declared is the one the question asks, not the one the engine
answers.** q007 asks "Which test covers capture?", so its subject is
`PaymentService.capture` even though the engine returns evidence only for
`PaymentService`. Declaring the class instead would have made the case pass by
tuning the corpus to current behavior, which is the exact move ADR-0003 exists
to forbid. q007 therefore still fails, and its failure is now a precise finding
rather than a shrug.

**4. The module-symbol ranking question is deliberately not answered here.**
See below.

## Consequences

`exact_symbol_resolution` moves 0.6154 → 0.6667 (24/39 → 26/39) from q005 and
q016 alone. Recall@10 moves 0.6508 → 0.6984.

**The evidence-precision rates fall: exact/valid 0.6618 → 0.6400 and containing
0.7353 → 0.7067.** This is not a regression to hide. Asking the correct subject
returns *more* evidence — the supporting relation edges — and per ADR-0003 a
call-site line rarely equals a gold range describing a definition, so the extra
items enlarge the denominator without matching spans exactly. Recall rose and
span precision fell for the same reason, and quoting either alone misrepresents
the change.

The target remains unmet: **0.6667 against 0.98.**

### Two open findings this exposes, both deferred on purpose

**Module-scoped graph queries rank the module's own symbol first.** For
`dependencies(module)` and `exports(module)` the service returns `src.client`,
`src.orders`, `src.payments.service` at rank 1 — the subject itself — ahead of
what it depends on or exports. q015's rank-2 *is* the expected `total`, and q017
returns `src.orders` twice where the two exports `Order` and `total` should be.
Whether a module's own symbol belongs in that evidence at all, and whether it
should outrank the relations asked for, is a product-contract question about
`GraphQueryService`, not an evaluation question. Bundling an engine change into
a measurement correction would make the moved baseline impossible to attribute —
the mistake ADR-0017 was careful to avoid and this record keeps avoiding.

**`related_tests` does not resolve a method subject to its class-level edge.**
The `TESTS` edge for `test_capture_uses_idempotency_store` is recorded against
`PaymentService`, because the test imports the class and calls the method on an
instance — correct per ADR-0004. But `related_tests("PaymentService.capture")`
returns nothing, so a user asking about the method is told nothing exists while
the edge sits one level up. Worth an explicit decision; do not "fix" it by
moving the edge, which would break ADR-0004's import-and-call rule.

## The correction

ADR-0017's consequences section states that the remaining gap is the
TypeScript/JavaScript graph intents and calls it "a genuine capability question
rather than a harness one". **Both halves are wrong**, and this record corrects
them:

- It is not TypeScript-specific. Three of the six affected cases are Python
  (q005, q007, q010); the language split was coincidence.
- It is not a capability gap. The engine answers `callers`, `dependencies`,
  `exports`, and `related_tests` on these fixtures; it was being asked the wrong
  question.

That claim was written from the widened-run output without probing the service
directly — the same shortcut that produced the original stale-fixture defect,
one investigation earlier. Three consecutive investigations have now found the
measuring apparatus at fault rather than the engine
(`exact_symbol_resolution`, `valid_evidence_rate`, and this). The evaluation
harness has had materially less scrutiny than the code it measures, and it is
the only thing standing between a reader and a false account of the product.
