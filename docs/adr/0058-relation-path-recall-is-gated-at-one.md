# ADR-0058: `relation_path_recall` is gated, absolutely, at 1.0

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (asked for the target to be set) and
  implementing agent
- Supersedes: none — it *discharges* the deferral ADR-0038 recorded
- Related: ADR-0038 (recall added beside precision, deliberately ungated),
  ADR-0057 (lexical answers carry their resolved edges), ADR-0032 and ADR-0033
  (thresholds and corpus-size granularity), ADR-0048 (reported, not gated),
  ADR-0023 (target profiles)

## Context

ADR-0038 added `relation_path_recall` beside the precision metric and left it
**deliberately ungated**, for a stated reason: two of ADR-0034's four causes
were still open, and "a threshold over an unsettled cause cannot be reasoned
about". Its register row named the trigger — *that design decision is settled*.

ADR-0055 settled the third cause and ADR-0057 the fourth. The metric now reads
**1.0000**, and the deferral's condition is discharged.

The user deferred choosing the number until it existed, rather than bundling it
with the change that moved it — the trap `extra_build.md` names explicitly, and
the shape ADR-0048 refused when it declined to lower a threshold to fit.

## The arithmetic, before the choice

The denominator is **24**: measured cases whose `expected_relations` is
non-empty. It is **not uniform** — 21 declare one edge, and one each declare
two, three and five — so the aggregate does not move in steps of 1/24. The
reachable values immediately below 1.0 are:

| Value | What produced it |
| ---: | --- |
| 1.0000 | every declared edge emitted |
| 0.9917 | q060 loses one of its five |
| 0.9861 | q059 loses one of its three |
| 0.9792 | q017 loses one of its two |
| 0.9583 | any single-edge case loses its only edge |
| 0.9167 | two single-edge cases |

So the candidate thresholds mean:

- **1.0** — absolute; any loss fails.
- **0.99** — tolerates *only* q060 losing one of five. It privileges one case by
  accident of how many edges it happens to declare, which is not a policy.
- **0.95** — tolerates exactly one whole-case miss.
- **0.90** — tolerates two.

## Decision

**Gate `relation_path_recall` at 1.0, on the `retrieval` profile only.**

**Absolute, for the reason `lexical_resolution` is absolute** (ADR-0032): this
is a *deterministic emission* question, not a ranking one. An edge the corpus
declares, the store holds, and resolution has already bound to a real target
either appears in the answer or it does not. There is no ranking, no model, and
no fuzziness for a tolerance to absorb.

**No tolerance has a named cause.** Nothing is known that can drop a declared,
stored, resolved edge legitimately. A bounded traversal or a
`MAX_RELATION_PATHS` truncation that lost one would be a defect or a mis-set
bound — something to fail on, not to absorb. A threshold chosen to swallow a
failure nobody can name is exactly what ADR-0048 refused: *a number chosen to be
passed says less than it appears to.*

**This is not ADR-0033's situation.** 0.98 was kept there because it is a
Section 19.3 release commitment whose wording should not be edited to suit an
artifact of corpus size. `relation_path_recall` appears in no release table; it
is an internal gate over a measured behaviour, which is precisely the case where
ADR-0032 ruled that stating what the gate does beats stating something looser
that selects the same pass/fail set.

### Retrieval profile only, and why that is load-bearing

The target is registered inside the `retrieval` branch, not the shared
`minimums` table. **The semantic corpus declares zero relations in all 14
cases**, so its aggregate is `None`, and `_unmet_targets` treats `None` as a
miss. Putting the target in the shared table would have failed the Phase 7
conceptual gate on a metric that corpus cannot express — ADR-0023's mistake
exactly, a corpus held to an instrument written for a different one.

## Measured

| Artifact | Effect |
| --- | --- |
| `baseline-phase-4` | `relation_path_recall` 1.0, target met; `unmet_targets` unchanged at `['changed_symbol_precision']` |
| `baseline-phase-3` | same, unchanged |
| `baseline-phase-0` | **gains `relation_path_recall`** in `unmet_targets`, joining six others |
| Phase 7 / conceptual | unaffected — the target is not in its profile |

The null baseline gaining the entry is correct rather than incidental: it
asserts "nothing is implemented, so nothing is found", and a gate it does not
miss would be a gate that asks nothing.

## The gate was mutation-checked, because a threshold that cannot fail is decoration

Adding a target that the corpus already satisfies produces a green run whether
or not the gate is wired to anything. So the regression was induced: lexical
answers were made to stop emitting relation paths — reverting ADR-0057's
behaviour without touching the threshold.

```
relation_path_recall: 1.0    -> 0.875
unmet_targets: ['changed_symbol_precision']
            -> ['changed_symbol_precision', 'relation_path_recall']
```

The gate caught it. The source was then restored from a file copy — never
`git checkout --`, which has twice reverted the fix along with the mutation
(ADR-0022, ADR-0042) — and all three baselines reproduce byte-for-byte.

## Alternatives

**0.95, tolerating one whole-case miss.** Rejected: the tolerance has no named
cause, and every mechanism that could consume it is a defect worth failing on.

**0.99.** Rejected as arbitrary — it tolerates one specific case losing one of
its five edges and nothing else, which is a property of the corpus's shape
rather than a policy about correctness.

**Leave it ungated, as ADR-0048 left `containing_evidence_rate`.** Rejected on
the distinction ADR-0038 itself drew: that metric is *precision* and punishes
the completeness ADR-0020 requires, so gating it would penalise compliance.
This one is *recall* against edges the corpus explicitly declares, and nothing
about emitting more can lower it.

## Consequences

- **Any regression that drops a declared edge now fails the Phase 3 and Phase 4
  gates.** That is the point, and it is the first gate protecting relation
  paths since they were introduced.
- ADR-0034's cause list is discharged *and* its metric is now defended, so the
  register row closes rather than being re-deferred.
- `baseline-phase-0` changes by one line. `-3` and `-4` do not change at all
  beyond what ADR-0057 already moved.
- **A corpus author adding a case that declares an edge the engine cannot emit
  will fail this gate.** That is intended: ADR-0036 already requires an
  expectation to name something the engine can produce, and this makes the
  requirement enforced rather than advisory.

## Security and Privacy

None. A threshold in the evaluation runner; no runtime behaviour, data movement,
or logging changes.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`, `SCHEMA_VERSION` stays `14`. Rollback is removing the two-line entry and
regenerating `baseline-phase-0`.

## Approval

The user asked for the target to be set on 2026-08-17, having deliberately
deferred it earlier that day until ADR-0057's number was known. The value and
its absoluteness are the implementing agent's recommendation, recorded here with
the arithmetic and the rejected alternatives so it can be overridden on the
evidence rather than re-derived.
