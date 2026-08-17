# ADR-0059: A graph expectation declares direct results

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (ruling given 2026-08-17) and implementing agent
- Supersedes: none
- Related: ADR-0052 (a claim may not outrun its citation), ADR-0020 (relations in
  every graph answer), ADR-0018 (graph query subject), ADR-0036 (expectations
  name real symbols), ADR-0003 (the corpus is never edited to move a number),
  ADR-0026 (exact-match ranking), ADR-0033 (threshold granularity)

## Context

Traversal runs to `max_depth` 2, so a `CALLERS` or `DEPENDENCIES` answer
routinely contains symbols reached through an intermediate. Nobody had ruled
whether the corpus should declare them, and the question blocked Task 6 —
because a case cannot be written to be ranking-sensitive without first knowing
whether the extra symbols are answers or noise.

Two concrete instances:

| Case | Question | Returned | Declared |
| --- | --- | --- | --- |
| q005 | "What calls `IdempotencyStore.claim`?" | `PaymentService.capture` (direct), `test_capture_uses_idempotency_store` (via capture) | capture, and the subject |
| q015 | "What does `client` import?" | `total` (direct), `Order` (via total) | `render`, `total` |

## Decision

**A graph expectation declares direct results only.**

Indirect results may still be *returned* — ADR-0052 already requires the engine
to label them, so a depth-2 claim reads "reaches Y indirectly, through Z" rather
than asserting a direct call. The corpus declares what the question directly
asks.

**This is what makes `exact_symbol_resolution` a ranking gate rather than only a
resolution gate.** With a genuine indirect result present and undeclared, the
metric asks whether the **direct** answer ranks first — a real property, and one
a reversal breaks. Declaring every returned symbol would make any order pass.

The stated cost is accepted: an undeclared true indirect answer counts against
`relation_path_correctness` and the evidence rates. That is ADR-0038's shape —
precision penalising completeness — and ADR-0048's resolution applies: those
metrics are reported, and recall is what is gated.

## The premise this task carried did not survive

Three claims in the work plan were checked and two are wrong.

**The counts have drifted.** The plan states "distractor presence and reversal
sensitivity are the same 9 cases, exactly". Measured today: **11 reversal-
sensitive, 12 returning a distractor, and not the same set** — q026 returns a
distractor without being sensitive. The drift is partly this project's own
doing: ADR-0051 re-typed q006, ADR-0053 made `CONCEPTUAL` measurable, and
ADR-0057 changed what q024 and q029 return.

**"Fixing them would take symbol-intent ranking coverage to zero" is wrong.**
Correcting q015 leaves `['total']` against a returned `['total', 'Order']`, and
`Order` is a depth-2 result — so q015 stays reversal-sensitive. Coverage was
never at risk from that fix.

**"Ranking sensitivity is structurally unavailable for a correctly-specified
direct graph case" is refuted by this ruling.** Under direct-only, sensitivity
needs a **two-hop chain**, not an under-specified expectation. The 24 cases
added on 2026-08-15 were not sensitive because **`symbol_breadth` contains no
two-hop call chain** — nothing calls `run_pipeline` or
`test_pipeline_advances` — which is a fixture-shape limit, not a structural one.

## Changes

**1. q015 corrected.** It asked "What does `client` import?" and expected
`['render', 'total']`. `client.js` **defines** `render` and imports only
`total`, so `render` was a factually wrong answer and the engine was right never
to return it. Corrected on ADR-0036's rule — an expectation must name something
the engine can produce — the same ground as ADR-0035 and ADR-0039. Ruled by the
user rather than assumed, because any correction moves a number and ADR-0003 is
strict about why.

**2. `symbol_breadth` gains a two-hop chain.** `start_pipeline` calls
`run_pipeline`, which calls `OrderPipeline.advance`. This is *adding coverage*,
which ADR-0003 permits, and it is the smallest edit that lets the newer fixture
express what the older ones could.

**3. q065 added**, asking "What calls `run_pipeline`?" so the new symbol is
queried rather than sitting in the fixture untested. It declares the direct
caller and the edge; its reference site was derived from the source file, not
from the engine's output.

## Measured

| Metric | Before | After |
| --- | ---: | ---: |
| `symbol_recall_at_10` | 0.8917 | **0.9016** |
| `ndcg_at_10` | 0.9173 | **0.9250** |
| `primary_evidence_recall_at_10` | 0.9368 | 0.9375 |
| `containing_evidence_rate` | 0.7537 | 0.7500 |
| `exact_evidence_rate` / `valid_evidence_rate` | 0.6567 | 0.6544 |
| `relation_path_correctness` | 0.8646 | 0.8633 |
| `exact_symbol_resolution` | 1.0000 | **1.0000** |
| `relation_path_recall` | 1.0000 | **1.0000** |

`unmet_targets` stays `['changed_symbol_precision']`, the accepted structural
miss. ADR-0058's new absolute gate on `relation_path_recall` still passes.

The four small precision dips are the declared cost above: `start_pipeline
CALLS run_pipeline` is a true edge that most cases do not declare, so it
enlarges denominators without matching them.

**q053 is now reversal-sensitive** — the first case added after 2026-08-15 to be
so, which is what Task 6 asked for. The symbol-intent sensitive set is q003,
q005, q015, q053. q065 is deliberately *not* sensitive: everything it returns is
expected, which is correct for a direct one-hop question.

### The denominator moved, and was checked before it did

`exact_symbol_resolution` scores **51** cases now, up from 50. One miss scores
**0.9804** and still clears the 0.98 target; two score 0.9608 and fail. The
margin is unchanged at exactly one miss — the condition ADR-0033 wanted, and the
check `extra_build.md` demands before any symbol-intent case is added.

## Two findings recorded, not fixed

**q005 and q053 declare their own subject, which the engine does not return.**
q005 expects `IdempotencyStore.claim` among the callers of
`IdempotencyStore.claim`, and q053 expects `OrderPipeline.advance` among its own
callers. Nothing calls itself here, so both lose recall for declaring it.

This is **not** the ADR-0018 violation it first looks like. That record
explicitly allows a self-referential case — "absent means `expected_symbols[0]`,
which is correct for every exact, lexical, and self-referential case" — and it
separately records that module-scoped queries *do* return the subject first. The
first reading of this, that nine cases contradicted ADR-0018, was wrong and is
corrected here rather than left in a working note.

Whether a `CALLERS` expectation should ever name its own subject is a narrower
question than the one ruled today, and it is left open with a register row.

## Alternatives

**Declare transitive results too.** Rejected by the ruling: once every returned
symbol is expected, any order passes, and symbol-intent ranking coverage goes to
zero — leaving only the lexical intents measuring order, where ADR-0026 already
rules.

**A separate `expected_transitive_symbols` field.** Rejected as
disproportionate: `QueryCase` is `extra="forbid"`, so it needs a model change, a
scorer change, and a shape change to every tracked baseline — the same
constraint that blocked extending the change corpus during the ADR-0016 work.

**Reduce `max_depth` for these intents.** Rejected: it narrows real answers to
suit a metric, which inverts the priority ADR-0046 set.

## Consequences

- Task 6's "done when" is satisfied on its first branch: the convention is ruled
  and a ranking reversal now fails a case added after 2026-08-15.
- **`extra_build.md` has no tasks left.** Its own instruction is to delete it
  rather than leave it to rot, which is now a live action rather than a future
  one.
- The corpus is **65 query cases / 28 change cases** over 7 fixtures, with a
  scored symbol-intent denominator of 51.
- No source change. No contract, schema, or migration change;
  `contract_version` stays `1.1` and `SCHEMA_VERSION` stays `14`. **No parser,
  resolver, or chunker version moves, so no re-index is required** — the fixture
  gained a function, which is ordinary corpus content.

## Security and Privacy

None. Corpus data and one fixture function; no runtime behaviour changes.

## Migration and Rollback

Not applicable beyond regenerating `baseline-phase-3` and `-4`. Rollback is
reverting the commit and regenerating them again.

## Approval

Ruled by the user on 2026-08-17: direct results only, and q015 corrected. The
fixture extension and q065 follow from the ruling and are recorded here for
review.
