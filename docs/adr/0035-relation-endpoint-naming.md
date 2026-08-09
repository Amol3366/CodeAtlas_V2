# ADR-0035: A relation endpoint is named by the symbol's qualified name

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: ADR-0003 (the corpus is not edited to fit the engine), ADR-0031 (the
  q019 naming ruling and the test that separates a correction from gaming),
  ADR-0034 (which decomposed the metric and left this cause open)

## Context

ADR-0034 decomposed `relation_path_correctness` into four causes and fixed one.
This settles the second: three cases where the corpus and the engine spell a
module differently.

| Case | Corpus declared | Engine emits | Module symbol that exists |
| --- | --- | --- | --- |
| q015 | `client IMPORTS total` | `src.client IMPORTS total` | `src.client` |
| q017 | `orders EXPORTS Order` | `src.orders EXPORTS Order` | `src.orders` |
| q010 | `service IMPORTS idempotency` | `src.payments.service IMPORTS **IdempotencyStore**` | `src.payments.service` |

**The bare names name nothing.** No symbol `client`, `orders`, or `service`
exists in any fixture; the module symbols are `src.client`, `src.orders`,
`src.payments.service`. The corpus was referencing identifiers the system cannot
produce.

Unlike q019, the corpus is **internally consistent** here — it writes every
module bare. That consistency is why this needed its own ruling rather than
following ADR-0031 automatically.

## Decision

**A relation endpoint is named by the symbol's qualified name.** The three
source endpoints and q017's two targets are qualified in the corpus.

### Why this is not the edit ADR-0003 forbids

ADR-0031 recorded the test to apply, and it is worth restating because this case
is closer to the line:

> If the engine emitted `README.Health` and the corpus declared `Health`,
> changing the corpus would be gaming.

The engine here emits `src.orders` and the corpus declared `orders`, so the
surface shape *is* "corpus changed to match engine". What makes it legitimate is
narrower and checkable: **the declared name is not a symbol.** An expectation
must reference an identifier the system can produce, or it is not an expectation
about behaviour — it is unsatisfiable by construction, exactly as
`README.Health` was.

The corpus already qualifies a method by its class (`PaymentService.capture`,
q005 and q007). Qualifying a module by its package is the same rule applied one
level up, not a new convention.

The alternative — teaching the engine to emit bare module names — would change
the identity of every module symbol in the product to suit three expectation
strings, and would make `src.orders` and `tests.orders` indistinguishable.

### q010 is deliberately only half-fixed

q010 disagrees **twice**, and only one disagreement is naming.

Its source is qualified with the rest. Its target is left alone: the statement
is `from .idempotency import IdempotencyStore`, so the corpus claims the import
targets the **module** `idempotency` while the engine records the **class**
`IdempotencyStore` the statement actually binds.

That is a semantic claim about what an `IMPORTS` edge points at, not a spelling.
The engine's reading is also the one ADR-0021's import-and-call rule depends on —
a class import is evidence about its methods, which is only meaningful if the
edge names the class. Changing it here would quietly settle a modelling question
inside a naming fix.

**q010 therefore still scores 0.0000, now for one stated reason instead of two.**

## Measured

| Metric | Before | After |
| --- | ---: | ---: |
| `relation_path_correctness` | 0.5000 | **0.6364** |

Per case: q017 **0.0000 → 1.0000**; q015 **0.0000 → 0.5000**; q010 unchanged at
0.0000.

**No other metric moved on any baseline.** `baseline-phase-7` and
`rerank-phase-7` are untouched — the conceptual corpus declares no relations.

**q015 reaching only 0.5 is the point worth keeping.** Its expectation now
matches, and precision still halves the score because the engine also emits
`total REFERENCES Order` — a second, *true* edge the corpus did not declare.
That is the remaining cause ADR-0034 named: precision penalises the
every-supporting-edge behaviour ADR-0020 deliberately mandates. Naming was never
going to fix it.

## Consequences

- The corpus's relation endpoints now reference symbols that exist, which is
  checkable rather than a matter of taste. A dataset validator asserting that
  property would catch this whole class — including q019 — and is worth
  considering, but needs the fixtures indexed and is not built here.
- `relation_path_correctness` is at 0.6364 with **two causes left**: q005 and
  q015's precision penalty, and q027/q029's lexical intents emitting no paths.
  **It still should not get a gate target** until those are settled.
- `baseline-phase-0`, `-3`, `-4` regenerated; `-1` and `-2` untouched as frozen
  history.

## Alternatives

**Emit bare module names from the engine.** Rejected: it changes module symbol
identity product-wide to suit three strings, and collapses `src.orders` and
`tests.orders`.

**Also change q010's target to `IdempotencyStore`.** Rejected as out of scope —
it settles what an `IMPORTS` edge points at, which is a modelling decision
deserving its own record, not a line in a naming fix.

**Compare endpoints by suffix in the harness.** Rejected. It hides the
disagreement rather than resolving it, and `a.b.foo` would match `c.d.foo` —
trading a visible failure for a silent false pass.

## Security and Privacy

None. Four expectation strings in an evaluation corpus.

## Migration and Rollback

No schema, contract, code, or version constant changes. Rollback is reverting
the commit and regenerating the three baselines.

## Approval

Approved by the user on 2026-08-10, directing the module naming convention be
fixed after ADR-0034 recorded it as one of the metric's remaining causes.
