# ADR-0031: A document section is named by its bare heading

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: ADR-0003 (the corpus is not edited to fit the engine), ADR-0018 and
  ADR-0024 (the harness asking a question the corpus did not pose)

## Context

The corpus used **two naming conventions for the same kind of thing**. Three
`DOCUMENT_LOOKUP` cases name a markdown section:

| Case | Declared | Emitted by extraction |
| --- | --- | --- |
| q019 | `README.Health` | `Health` |
| q027 | `Order flow` | `Order flow` |
| q031 | `Order flow` | `Order flow` |

Extraction emits **bare** heading names everywhere — `Sample Service`,
`Health`, `Order flow` — and no file-stem qualification exists anywhere in the
engine. `README.Health` therefore names a symbol the system cannot produce, and
it disagrees with the corpus's own other two cases.

This had been carried as an open ruling since ADR-0024, with the standing note
that expectations must not be edited to move a number.

### The part that changes the character of the fix

`expected_symbols[0]` is not only what the scorer compares against. It is **the
query the harness issues**: `_query_term` returns `case.query_subject` when
present and `expected_symbols[0]` otherwise.

So q019 was asking the engine to find `README.Health`. Nothing can resolve that,
so the engine returned nothing and abstained — **correct behaviour on an
impossible query** — and was then scored as a wrong abstention on a case
declaring `expected_abstention: false`.

The corpus was not merely mis-labelling the answer. It was **posing an
unanswerable question and recording the engine's correct refusal as a miss.**
That is the same shape as ADR-0018, where the harness asked who calls `render`
for a case about `total`, and ADR-0024, where a case the adapter never ran was
scored as answered wrongly.

## Decision

**A document section is named by its bare heading text. q019's expectation
changes from `README.Health` to `Health`.**

One line of `tests/evaluation/cases/queries.json`. No fixture, question,
intent, evidence range, or forbidden claim is touched, and no engine code
changes.

### Why this is not the edit ADR-0003 forbids

The distinguishing test, stated so it can be applied again:

> If the engine emitted `README.Health` and the corpus declared `Health`,
> changing the corpus would be gaming — adjusting the expectation to match
> behaviour.

That is not this case. Here the corpus **contradicts itself**, and the ruling
adopts the convention already used by two of its three cases, which is also the
only convention the engine can produce. The alternative — teaching extraction to
qualify headings with a file stem — would change one case's outcome by inventing
a naming scheme nothing else uses, purely to make an outlier expectation
correct.

## Measured

One line moved five metrics, on both live baselines:

| Metric | Before | After |
| --- | ---: | ---: |
| `lexical_resolution` | 0.8750 | **1.0000** (8/8) |
| `mean_reciprocal_rank` | 0.9714 | **1.0000** |
| `abstention_correctness` | 0.9714 | **1.0000** |
| `ndcg_at_10` | 0.9051 | 0.9337 |
| `symbol_recall_at_10` | 0.8857 | 0.9143 |

`lexical_resolution` leaves `unmet_targets` on `baseline-phase-3` and
`baseline-phase-4`.

**A one-line corpus edit moving five metrics is exactly the leverage ADR-0003
exists to restrain, and the size of the movement is not evidence that the change
was right.** It is explained by the mechanism above: the edit changes the
*input* the engine is given, not merely the string it is compared against. An
impossible query became a possible one.

`abstention_correctness` reaching 1.0000 is the clearest signal of that. No
abstention logic changed; the engine simply stopped being asked for a symbol
that cannot exist.

The evidence rates barely move and one falls slightly
(`exact_evidence_rate` 0.5647 → 0.5632 on `baseline-phase-4`), which is the
expected signature: one case now returns evidence where it previously returned
none.

## Consequences

- **The bare-heading convention is now the corpus's single rule** for naming a
  document section, matching extraction.
- **Ambiguity is the cost, and it is real.** Two files with a `## Health`
  heading would both emit `Health`. This corpus has no such collision, so the
  ruling is safe here and is *not* a general claim that bare headings are
  sufficient identifiers. A repository with repeated headings would need
  qualification — and if that is ever built, it must be built as a real
  extraction rule for every document, not for one case.
- **`lexical_resolution`'s threshold question is now less urgent but not
  answered.** At 8/8 the metric reads 1.0000 and the provisional 0.90 passes.
  The original objection stands: with eight scorable cases every value is a
  multiple of 0.125, so 0.90 still means "8 of 8" and can express nothing
  finer.
- `baseline-phase-0`, `-3`, and `-4` regenerated. **`baseline-phase-1` and `-2`
  deliberately untouched** — frozen history whose gate scripts are marked
  SUPERSEDED.
- `baseline-phase-7` is unaffected: the conceptual corpus is a different dataset
  and contains no such case.

## Alternatives

**Qualify headings with the file stem in extraction.** Rejected: it invents a
naming scheme nothing else in the product uses, changes every document symbol in
every repository, and exists only to make one outlier expectation correct.

**Change q027 and q031 to the qualified form instead.** Rejected: it would move
the corpus *away* from what the engine emits, making three cases fail instead of
one, and would still require the extraction change above.

**Leave the inconsistency.** Rejected by the ruling. It was a standing open item
that made `lexical_resolution` unreachable and quietly recorded a correct
abstention as a defect.

## Security and Privacy

None. A corpus expectation string changed; no code, data movement, or
configuration.

## Migration and Rollback

No schema, contract, or version constant changes. Rollback is reverting the
commit and regenerating the three baselines.

## Approval

Approved by the user on 2026-08-10, who ruled that q019 should use the bare name
and directed the corpus be updated to match.
