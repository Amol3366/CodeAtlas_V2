# ADR-0032: `lexical_resolution` is gated at 1.0, which is what 0.90 already meant

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Amends: ADR-0023, which introduced the threshold and recorded it as provisional

## Context

ADR-0023 added `lexical_resolution` to gate `CONFIG_LOOKUP` and
`DOCUMENT_LOOKUP`, at a threshold of 0.90 chosen "to match the recall family
rather than for the number it produces" and explicitly recorded as provisional.
Setting it properly has been an open item since, on the stated objection that
the corpus is too small for the value to mean anything.

The arithmetic confirms the objection and is sharper than it was recorded.

**The metric scores eight cases.** Ten declare a lexical intent; `q037` and
`q039` sit on the `malicious_unsupported` fixture and are excluded by ADR-0024,
which keeps a case the adapter never ran out of every accuracy aggregate. Eight
cases means the metric can only take values that are multiples of 0.125:

```text
8/8 = 1.000    7/8 = 0.875    6/8 = 0.750    5/8 = 0.625
```

| Threshold | Requires | Failures tolerated |
| --- | --- | ---: |
| **0.90 (existing)** | 8/8 | **0** |
| 0.875 | 7/8 | 1 |
| 1.0 | 8/8 | 0 |

**0.90 and 1.0 select exactly the same pass/fail set.** The gate has always
demanded every scored case while reading as though a miss were acceptable.

## Decision

**Set the threshold to 1.0.**

This changes no outcome. Both live baselines reproduce byte-for-byte after the
change, which is the evidence that it is a restatement rather than a
tightening. What changes is that the number now says what the gate does.

Absolute is also the right shape for what is being measured. These are
deterministic lookups: a configuration key or a document heading either resolves
or it does not, and there is no probabilistic component to leave headroom for.
Section 19.3's other deterministic targets are already absolute — evidence
validity 100%, active-snapshot leakage 0, incremental indexing correctness 100%
— and ADR-0023 set `containing_evidence_rate` at an explicit 1.0 on the same
reasoning.

Three tests pin the *reasoning* rather than the constant: that the threshold
tolerates no failures at this corpus size, that the replaced 0.90 selected the
same set, and that any invented value between 0.875 and 1.0 is unreachable. The
second is the one that matters over time — **if the corpus grows, it fails**,
and the threshold becomes a real decision again rather than a spelling choice.

## The same illusion exists elsewhere, and is not fixed here

`exact_symbol_resolution` has **27 scored cases against a 0.98 threshold**,
which requires **27/27 and tolerates zero failures**. It reads like "one miss
allowed on 27 cases" and is not.

That number comes from the Section 19.3 target table and has been cited in
approved phase gates, so correcting it is a larger decision than this one and is
**deliberately left open** rather than folded in. It is recorded here because
the pattern is the point: a fraction below 1.0 is only meaningful if the corpus
is large enough to express it, and two of this project's thresholds are not.

## Alternatives

**0.875, tolerating one failure.** This would be a genuine loosening — the only
value that actually differs from the current behaviour — and would need
justifying on its own terms, not as a tidy-up. Nothing argues for it: the one
case that was failing, q019, turned out to be a corpus defect (ADR-0031) whose
correct fix was fixing the corpus.

**Leave 0.90.** The gate keeps working and its stated value keeps misleading
anyone reading the target table. The objection that has been open since
ADR-0023 stays open.

**Grow the corpus so the threshold has granularity.** Worth doing on its own
merits, but it is corpus work with its own considerations and does not depend on
this ruling. The threshold would then need revisiting, which the second test
forces.

## Consequences

- No measured outcome changes; both baselines reproduce byte-for-byte.
- A future author cannot quietly set 0.95 and believe they have relaxed the
  gate — the third test rejects any value that is unreachable at this size.
- If a ninth scored lexical case is added, the second test fails deliberately,
  because 0.90 and 1.0 would then differ and the choice becomes real.
- `exact_symbol_resolution`'s 0.98 remains as recorded above: an open item, not
  a defect introduced here.

## Security and Privacy

None. A gate threshold constant, with no data movement or behaviour change.

## Migration and Rollback

No schema, contract, corpus, or version constant changes. Rollback is reverting
the commit; no artifact needs regenerating, because none moved.

## Approval

Approved by the user on 2026-08-10, choosing 1.0 after the arithmetic showed
0.90 already required every scored case.
