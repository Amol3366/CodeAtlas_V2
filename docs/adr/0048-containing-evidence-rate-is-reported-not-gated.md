# ADR-0048: `containing_evidence_rate` is reported, not gated

- Status: accepted
- Date: 2026-08-16
- Decision owners: user/product (ruling given 2026-08-16) and implementing agent
- Supersedes: none — it changes the gate on a metric ADR-0027 introduced, and
  leaves the metric itself untouched
- Related: **ADR-0038** (relation path recall — the same shape, resolved the
  same way), ADR-0020 (relations in every graph answer), ADR-0027 (containment
  recall), ADR-0003 (evidence granularity), ADR-0047 (graph evidence is the
  reference site)

## Context

`containing_evidence_rate` has been gated at **1.00** and has never met it. The
per-case investigation of 2026-08-15 and the corrections of ADR-0047 established
what it actually measures.

It is **precision**, not recall: `containing / predicted` summed over every
evidence item the engine emits across the whole corpus. An item counts only if
it covers a range the corpus declared. So the metric asks:

> Did the engine emit **nothing beyond** what the corpus wrote down?

**That question is in direct conflict with an accepted decision.** ADR-0020
requires every graph answer to populate `relation_paths` with *every supporting
edge*, and each edge carries evidence. An answer that cites five supporting
locations against a case declaring one scores 1/5 — for being complete.

## The ceiling calculation

This is the whole argument, so it is recorded here rather than only in a
handoff entry. Measured 2026-08-16, after ADR-0047 and the `git_changes` fixture
correction:

| | |
| --- | ---: |
| today | **93 / 123 = 0.7561** |
| cases still below recall 1.0 | 3 — q006, q032, q035 |
| **credit all three fully** | **95 / 123 = 0.7724** |
| items still uncredited at that ceiling | **28** |

**Even if every remaining failing case were fixed, the metric reaches 0.7724
against a 1.00 target.** The 28 items left over are not errors. They are correct
supporting evidence the corpus never declared — q060 cites 5 items against 1
gold, c021 4 against 1, q058 and q059 3 against 1. Each is a real location
supporting a real claim.

The gap cannot be closed by improving the engine. It can only be closed by the
engine emitting *less*, which ADR-0020 forbids, or by the corpus declaring every
supporting location of every case, which is not what a gold expectation is for.

*(An earlier figure of 0.8115 appears in the 2026-08-15 handoff. It was computed
before ADR-0047 and the fixture correction and is superseded; the ceiling is
lower now, not higher, because `target/` contributes evidence that no
expectation declares.)*

## Decision

**Remove the gate. Keep the metric.**

Following **ADR-0038 literally**, which faced precisely this shape:
`relation_path_correctness` scored precision, so every true edge the engine
emitted that the corpus had not declared lowered it — while ADR-0020 *required*
emitting those edges. ADR-0038 added recall beside it and left precision
ungated rather than deleting it or loosening it.

Three parts:

1. **`containing_evidence_rate` is no longer a gate condition.** A precision
   metric that cannot reach its target while the engine obeys an accepted
   decision is a metric punishing compliance.
2. **It is still computed and still reported**, unchanged. **Retaining the
   number matters**: every tracked baseline carries it, and removing it would
   quietly change what those artifacts mean. Its movement remains informative —
   a sharp fall still says something got noisier.
3. **`containing_evidence_recall_at_10` keeps its 0.90 gate**, and now meets it
   at 0.9706. Recall is the honest question for this corpus: *did the answer's
   evidence surface?* That is what a reader needs, and unlike precision it does
   not penalise completeness.

## Alternatives considered

**Lower the threshold to something reachable** — 0.75, say. Rejected: it would
be a number chosen to be passed rather than a statement about correctness, and
it would still drift every time a case declaring one gold item is added. ADR-0032
and ADR-0033 are the precedent for refusing thresholds that mean less than they
appear to.

**Change the metric to per-case precision, or cap predicted at the gold count.**
Rejected as re-defining a measurement to make it pass — the same objection, one
level down, and it would break comparability with every tracked baseline.

**Require the corpus to declare every supporting location.** Rejected: a gold
expectation states what the answer *must* contain, not an exhaustive
transcription of everything a correct answer may cite. It would also make every
case brittle against a legitimate new edge.

## Consequences

- One fewer gate condition. `unmet_targets` loses `containing_evidence_rate`;
  the value is still in every report and baseline.
- **The Phase 4 gate's remaining unmet target is `changed_symbol_precision`**
  (0.9464 against 0.95), which is closed as structural — c020–c022 split one
  physical diff into three cases that count each other's symbols.
- No engine change, no corpus change, no contract change. `contract_version`
  stays `1.1`; no version constant moves, so no snapshot is stale.
- Baselines are regenerated once, after this lands, so the movement is
  attributable to ADR-0047 and the fixture correction rather than to this.
