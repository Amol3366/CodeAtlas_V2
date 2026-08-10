# ADR-0038: Relation paths are scored by recall, not precision

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none

## Context

`relation_path_correctness` has been scored since Phase 0 as
`_precision(predicted_relations, expected_relations)` — the share of the
engine's emitted relation paths that the corpus declared.

**ADR-0020 requires a graph answer to emit every supporting edge.** That was
its whole point: an MCP client asking "who calls X" was getting prose and
evidence with nothing machine-readable between them, and the fix was to stop
discarding the paths the traversal had already computed.

So the two records are in direct conflict. Every *true* edge the engine emits
that the corpus did not happen to declare lowers this metric. **The measurement
penalises the engine for obeying an accepted decision.**

ADR-0034 decomposed this metric into four causes and named the symptom —
"precision penalising truth (q005 — the engine emits two correct edges, the
corpus declares one … this metric punishes what another record requires)". It
then deferred it, and ADR-0035 hit the same wall from the other side: "q015
reaching only 0.5 is the lesson: its expectation now matches and precision
still halves it, because the engine emits a second *true* edge the corpus did
not declare. Naming was never going to fix that."

Both records saw it. Neither named the instrument as the thing to change.

This is the ADR-0027 shape exactly, and it is now the **fifth** instance in
this project of a number being low because the apparatus was wrong rather than
the engine: `SUPPORTED_FIXTURES` (ADR-0017), the graph query subject
(ADR-0018), unmeasured-scored-as-wrong (ADR-0024), exact-span evidence recall
(ADR-0027), and this.

## Decision

**`relation_path_recall` is added beside `relation_path_correctness` and asks
the question the corpus can actually answer: did every declared relation
appear?**

- `relation_path_correctness` is **retained and unchanged.** Every one of the
  six tracked baselines keeps its current value and meaning. This is the
  ADR-0003 precedent, applied for the fourth time (`valid_evidence_rate`,
  `exact_evidence_rate`, `primary_evidence_recall_at_10`, now this).
- It reuses the existing `_recall` helper at `runner.py:892` rather than
  introducing a second one. Two copies of a scoring rule is how the
  `--format pr` and `_SEVERITY_ORDER` defects happened.
- **It is deliberately ungated.** No target is set, and that is the decision,
  not an omission — see below.
- The Markdown report is **not** given a row for either number. It never had
  one, and surfacing a metric in the human report should follow it earning a
  gate target, not precede it.

### Why no gate target

ADR-0034 established that this metric averages four unrelated causes and that
"a threshold over four different things cannot be reasoned about" — the
ADR-0023 lesson. Two causes are now settled (ADR-0035's naming, and this
record's instrument). Two remain:

- **q027 and q029 emit no relation paths at all** though their edges are
  stored, because lexical intents do not populate `relation_paths`. A design
  decision, unexamined.
- **q010** is a modelling question — does `IMPORTS` target the module or the
  bound class? — settled separately in ADR-0039.

A threshold set now would be a threshold over two unsettled causes. It is
recorded as owed once they are.

## Alternatives

**Replace precision with recall.** Rejected: six tracked baselines carry the
precision figure, and silently changing what a published number means is what
ADR-0003 exists to prevent. Retaining it costs one field.

**Score with F1.** Rejected: it re-imports the precision penalty at half
weight, so it still punishes ADR-0020 compliance — just less visibly, which is
worse. A number that is wrong for a legible reason beats one that is wrong for
a blended one.

**Change the engine to emit only declared edges.** Never seriously considered,
and recorded so nobody proposes it: it would tune the product to the corpus,
which is the exact inversion ADR-0003 forbids, and it would undo ADR-0020.

**Expand the corpus to declare every true edge.** Legitimate, and rejected for
scope: it means auditing every relation case against live engine output, it
grows with the engine, and it would still leave precision punishing any edge
added later. Recall is invariant to that.

## Consequences

Measured on the main corpus, and the per-case detail matters more than the
aggregate:

| Case | Precision | Recall | |
| --- | ---: | ---: | --- |
| q005 | 0.5000 | **1.0000** | emits a true undeclared `test … CALLS PaymentService.capture` |
| q015 | 0.5000 | **1.0000** | emits a true undeclared `total REFERENCES Order` |
| q007, q013, q016, q017, q026, q032 | 1.0000 | 1.0000 | unaffected |
| q010 | 0.0000 | 0.0000 | ADR-0039 |
| q027, q029 | 0.0000 | 0.0000 | lexical intents emit no paths — open |

Aggregate `relation_path_correctness` **0.6364** (7/11) →
`relation_path_recall` **0.7273** (8/11). The two cases that move are exactly
the two ADR-0034 and ADR-0035 predicted, which is the evidence this addressed
the cause they identified rather than something else.

**No engine behaviour changed. Nothing outside `evaluation/` was touched, and
this must never be cited as uplift.** Diffing the regenerated baselines shows
one added key and *no changed value* — the correct signature for an additive
metric, and the check that proves the precision path was not disturbed.

Incidental finding, recorded rather than fixed: **the engine emits duplicate
relation paths** — `src.client IMPORTS total` appears twice in q015's output,
`PaymentService.capture CALLS IdempotencyStore.claim` twice in q005's. Scoring
compares sets, so no metric is affected, but a machine-readable list handed to
an MCP client should probably not repeat itself. Out of scope here; it is a
product question, not a measurement one.

`contract_version` `1.1`, `SCHEMA_VERSION` `14`, dataset contract `1.0`, all
parser/resolver/chunker versions untouched. No migration.

## Security and Privacy

None. Evaluation scoring reads a corpus of fixture repositories and touches no
repository content, provider, credential, or network path.

## Migration and Rollback

No migration. `QueryScore.relation_path_recall` defaults to `0.0` and
`AggregateMetrics.relation_path_recall` defaults to `None`, so every prediction
file and every artifact written before this record parses and scores exactly as
it did. Rollback is deleting the field.

`baseline-phase-0`, `-3`, and `-4` regenerated. **`baseline-phase-1` and `-2`
were deliberately not touched** — their gate scripts are marked SUPERSEDED and
document that re-running them exits 5 by design, so regenerating them would
overwrite the record those gates were approved on.

Both tests were observed failing before the implementation
(`AttributeError: 'QueryScore' object has no attribute 'relation_path_recall'`).
The first pins that an extra true edge does not reduce recall *and* that
precision still halves — asserting both, because a change to the precision
figure would silently move six baselines. The second pins that a missing
relation still reduces recall, so this cannot become a metric that only goes
up.

## Approval

Recorded by the implementing agent on 2026-08-10 as part of the project
closeout. No Section 25 item is triggered: no contract change, no schema
change, no engine change, no dependency.
