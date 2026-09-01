# ADR-0075: A graph case declares its traversal depth

- Status: accepted
- Date: 2026-09-02
- Decision owners: **user/product** (chose the depth this record lands on) and
  implementing agent (measured the alternative and framed the cost)
- Related: ADR-0059 (an expectation declares direct results), ADR-0052 (a claim
  may not outrun its citation), ADR-0023 (corpus vocabulary lives in one place),
  ADR-0003 (the corpus is not edited to move a number)
- Implements: ADR-0073 ruling 3. **Extends ADR-0059; overturns nothing.**

## Context

`GraphQueryRequest.max_depth` defaults to **2**, and every graph case in the
evaluation corpus silently took that default. ADR-0059 separately ruled that an
expectation declares **direct** results.

Those two facts do not fit together. A case declared depth-1 answers and was
scored against a depth-2 traversal, so the engine's true second-hop results were
undeclared and read as **distractors**. That is not a defect — it is precisely
what makes `exact_symbol_resolution` a *ranking* gate rather than only a
resolution gate, and it is why q003, q005, q015 and q053 are reversal-sensitive.
But it was implied rather than stated, and nothing in the corpus said so.

ADR-0073 ruling 3 made depth part of each case. It did not say what depth.

## The measurement, which points the other way

Every graph case was run at depths 1, 2 and 3 and checked for the smallest depth
at which **all its declared relations** are returned.

| Result | Cases |
| --- | ---: |
| Satisfied at depth 1 | **31 of 31** |
| Requiring depth 2 | 0 |

**Not one case needs depth 2 for anything it declares.** Read literally, "each
case declares the depth it needs" means declaring 1 everywhere.

A first attempt used a different criterion — the smallest depth returning every
`expected_symbols` entry — and reported 15 of 31 as unsatisfiable at any depth.
That criterion was wrong, not the corpus: most of those cases expect **their own
subject** back (q052 wants `renderList` among the callers of `renderList`), which
is the class ADR-0073 ruling 1 deliberately made permanently unsatisfiable.
**A criterion that disagrees with a standing ruling is the criterion's bug**, and
it is recorded here because it nearly became this record's evidence.

## Decision

**Every graph case declares `traversal_depth: 2` — the value it was already
getting.** The field is introduced carrying today's behaviour.

`QueryCase` gains `traversal_depth: int | None`, required for the five graph
intents and **forbidden** for every other intent. `GRAPH_INTENTS` moves into
`dataset.py` beside the rest of the corpus vocabulary, for ADR-0023's reason, and
the adapter passes the case's depth instead of taking the default.

## Why not depth 1, which is what the measurement says

Because the measurement answers a narrower question than the ruling asks.

Depth 1 satisfies every declared *relation*. It also **removes every depth-2
result**, and those results are the corpus's only distractors. Without them:

- `exact_symbol_resolution` stops being a ranking gate and becomes a resolution
  gate — with no distractor present, "does the right answer rank first" cannot
  fail while resolution succeeds;
- the four reversal-sensitive cases stop being sensitive, and the corpus loses
  its only reversal coverage entirely;
- ADR-0052's indirect-claim rendering ("reaches Y indirectly, through Z") stops
  being exercised by any case.

ADR-0073 states that ruling 3 **extends ADR-0059 rather than overturning it.**
Depth 1 everywhere would overturn it: ADR-0059's whole point was that leaving
indirect results undeclared is what gives the metric its ranking character.
Raising relation precision by deleting the distractors would be a number
improving because the measurement got easier — the failure ADR-0053 recorded.

## Consequences

- **No answer changes and no number moves.** The tracked Phase 3 and Phase 4
  baselines reproduce **byte-for-byte**, which is the evidence this is a contract
  change and not a case edit. ADR-0073 predicted this task would move a reported
  number; it does not, and that is the outcome rather than an omission.
- **Depth is now explicit**, so retuning it is a visible, arguable change with
  its own measurement rather than an invisible default. A future change to any
  declared depth fails `test_the_declared_depths_preserve_the_previous_default`
  and moves the baselines, which is the signal ADR-0073 asked to watch for.
- **A silently ignored field is refused.** A `traversal_depth` on a non-graph
  case raises, because a field that reads as though it controls something while
  controlling nothing is the shape ADR-0053 recorded.
- **The wiring needed its own test, and the corpus could not provide one.** With
  every case at depth 2 and the dataclass default also 2, deleting the
  `max_depth=` argument left **26 corpus-driven tests green** — verified by
  mutation. A stub that reads the constructed request pins it instead, and it is
  parametrised over depths 1, 2 and 3 because asserting only 2 would pass against
  a hard-coded default.
- **The corpus file was edited in place, not re-serialised.** A `json.dumps`
  round-trip rewrites all ~2600 lines and buries the 31 real insertions — the
  unrelated reflow ADR-0069's handoff had to strip out of four files. A test pins
  the file's own spacing convention.
- No schema, no migration, no `contract_version` move. The dataset contract stays
  at **1.0**: the field is additive for every corpus that has no graph cases, and
  the one corpus that has them ships its depths in the same change.

## Alternatives rejected

- **Depth 1 everywhere.** What the measurement literally supports, and rejected
  for the reasons above: it buys precision by deleting the corpus's only
  distractors.
- **A mixed assignment** — depth 2 for the four reversal-sensitive cases, 1 for
  the other 27. It preserves the ranking gate and captures most of the precision
  gain, and it was rejected because the split is chosen to protect a metric
  property rather than derived from what each case measures. That is choosing
  corpus values by their effect on a number, which ADR-0003 restricts.
- **Leaving depth implied.** The status quo, and the thing ADR-0073 ruled
  against.
