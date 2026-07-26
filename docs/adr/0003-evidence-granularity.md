# ADR-0003: Evidence Granularity Is Measured, Not Chosen

- Status: accepted
- Date: 2026-07-26
- Decision owners: user (ruling), implementing agent (record)
- Supersedes: none
- Refines: none

## Context

CodeAtlas emits evidence as whole structural units: a symbol chunk covers a
complete definition, a document chunk covers a complete heading section, a
configuration chunk covers a top-level key and its value block. The Phase 0
evaluation corpus was written expecting narrower ranges — the specific lines
that answer the question, not the structure that contains them.

The two disagree, and the disagreement is measurable. `valid_evidence_rate`
counts a hit only when a predicted `(snapshot, path, start, end)` tuple equals a
gold tuple exactly. Phase 1 emitted 5 evidence items of which 4 agreed (0.8000).
Phase 2 emits 13 of which 9 agree (0.6923). The rate fell while the engine got
strictly better at answering questions, because Phase 2 began answering
configuration and document lookups that Phase 1 abstained from, and those are
exactly the intents where structural ranges are widest.

Every one of the four disagreements names the **right file** and a range that
**contains or overlaps** the expected one. None is invented:

| Case | Predicted | Expected | Nature |
| --- | --- | --- | --- |
| `q009` | `src/payments/service.py` 7-11 | 10-11 | whole definition vs. sub-range |
| `q023` | `app.toml` 1-4 | 1-2 | `[server]` table vs. part of it |
| `q027` | `docs/flow.md` 1-5 | 1-3 | heading section vs. paragraph |
| `q031` | `docs/flow.md` 1-5 | 3-5 | heading section vs. paragraph |

Phase 1 raised `q009` as a single anomaly. Phase 2 turned it into a pattern and
made it the largest single contributor to the headline evidence metric. A
decision was required before Phase 4, where change analysis multiplies the
effect across every changed symbol.

Three options were presented at the Phase 2 gate:

- **A.** Narrow the engine's evidence to the matched lines within a chunk.
- **B.** Widen the corpus to expect structural ranges.
- **C.** Change neither; report exact and containing agreement separately.

## Decision

**Option C. Score containment separately.** Ruled by the user on 2026-07-26.

The evaluation runner reports two metrics where it previously reported one:

| Metric | Counts a hit when |
| --- | --- |
| `exact_evidence_rate` | The predicted range equals the expected range |
| `containing_evidence_rate` | The predicted range contains the expected range in the same file |

`valid_evidence_rate` is retained and is defined as the stricter of the two, so
no historical number silently changes meaning. All three are reported side by
side in every baseline from Phase 3 onward.

Scope of this decision:

- No engine change. Phase 1 and Phase 2 evidence *output* is unchanged.
- No corpus edit. The gold ranges stay as written.
- Every gate claim from Phase 3 onward MUST name which metric it used.
- The Phase 3 gate is measured against `containing_evidence_rate` for the
  Section 19.3 recall targets, with `exact_evidence_rate` reported alongside.

Containment is directional and file-scoped: a prediction contains an expectation
when both name the same file and `predicted.start <= expected.start` and
`predicted.end >= expected.end`. A prediction that merely *overlaps* — clipping
one end of the expected range — counts for neither metric. Overlap is not
containment: a citation that omits half the answer has not proven it.

## Alternatives

- **Option A — narrow the engine.** Would raise the metric immediately and is
  the cheap answer. Rejected because it optimizes for the corpus before the
  product knows which granularity a reader actually wants. A reader looking at a
  change-impact finding may well want the whole definition, not the three lines
  that matched a query. Narrowing now would bake in an answer to an unasked
  question and would have to be undone if Phase 5's evidence drawer wants
  structure.
- **Option B — widen the corpus.** Rejected for the stronger reason: it moves
  the target to meet the engine and destroys the corpus's value as an
  independent check. A corpus that is edited whenever it disagrees with the
  implementation measures nothing.
- **Report only `containing_evidence_rate`.** Rejected because it flatters. The
  gap between exact and containing agreement is real information about how
  precisely CodeAtlas can point at an answer, and collapsing to the generous
  metric would hide it.

## Consequences

- The gap stays open, stays instrumented, and stays visible in every baseline.
  This ADR does **not** resolve it.
- The question returns for decision in **Phase 5**, when the evidence drawer
  gives a real consumer whose needs can settle it. `SYMBOL_PART` ranges already
  make the narrower option feasible if that is where it lands.
- The baseline artifact **schema** changes, because two metrics are added.
  `scripts/check_phase2.ps1` therefore stops passing, exactly as
  `check_phase1.ps1` did when the Phase 2 engine advanced. It is marked
  superseded; the Phase 2 artifacts are kept unchanged as the record of that
  gate and are **not** regenerated.
- Three metrics instead of one is more to read. That cost is accepted
  deliberately: the alternative is one number that quietly means something
  different from what a reader assumes.
- `AggregateMetrics` gains two optional fields. Consumers that read
  `valid_evidence_rate` continue to work unchanged.

## Security and Privacy

None. This decision changes how a locally computed metric is reported. No data
movement, no new trust boundary, no logging change, and no repository content
enters an artifact that did not already contain it.

## Migration and Rollback

Forward: `AggregateMetrics` gains `exact_evidence_rate` and
`containing_evidence_rate`; `render_markdown` gains two rows; the Phase 3
baseline generator emits all three. No storage schema, no API contract, and no
persisted data is affected, so there is no database migration.

Verification: a runner test asserts the two metrics differ on a prediction whose
range strictly contains the expected range — 0 on exact, 1 on containing. That
case is the whole point of the decision, so it is tested directly rather than
inferred from aggregate numbers.

Rollback: remove the two fields and the two report rows. Because
`valid_evidence_rate` is unchanged in both definition and value, rollback
restores the previous artifact schema exactly and loses only the added
visibility.

## Approval

Ruled by the user on 2026-07-26, recorded verbatim in the `docs/plans/PLAN.md`
handoff entry of 2026-07-26T05:10:00Z: score containment separately, Option C of
the three presented at the Phase 2 gate. The scope approved is the reporting
change described above, explicitly excluding any engine or corpus edit, with the
underlying granularity question deferred to Phase 5.
