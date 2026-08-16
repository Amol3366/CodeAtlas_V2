# ADR-0053: A gated intent leaves the denominator, and that flatters the metric

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (ruling given 2026-08-17) and implementing agent
- Supersedes: none
- Corrects: **ADR-0051** (q006) — see "The correction to ADR-0051" below
- Related: ADR-0017 (evaluation fixture gate correction), ADR-0024 (unmeasured
  is not wrong), ADR-0023 (target profiles and metric scope), ADR-0034 (what a
  lexical answer does not carry)

## Context

Found while verifying Task 4's premise, which is not what it was looking for.

`SUPPORTED_INTENTS` did not contain `CONCEPTUAL`. `predict_exact_symbols` gates
on it before dispatch, so every `CONCEPTUAL` case was emitted as
`_abstention(measured=False)` and **never reached the engine at all**.

Two cases were affected. **q024 has never been measured**, since it was written.
And **q006 was moved into that state by ADR-0051 hours earlier**, when it was
re-typed from `TRACE_FLOW` to `CONCEPTUAL`.

## This is ADR-0017 on the neighbouring constant, and it fails the other way

ADR-0017 fixed exactly this class of defect for `SUPPORTED_FIXTURES`, and its
own record states that "the constant directly above it, `SUPPORTED_INTENTS`,
*was* maintained, with comments recording its Phase 2 and Phase 3 widenings".
That was true of the widenings it received. It was not true in general:
`CONCEPTUAL` never entered it.

**The two gates fail in opposite directions, and this one is more dangerous.**

| Gate | A gated case scores | Effect on the metric |
| --- | --- | --- |
| `SUPPORTED_FIXTURES` | `False` | stays in the denominator as a **miss** — reports capability as failure |
| `SUPPORTED_INTENTS` | `measured=False` | **leaves the denominator** — removes a failing case from the average |

A gate that under-reports is loud: someone eventually asks why a working feature
scores zero, which is how ADR-0017 was found. A gate that removes a failing case
is silent, because every number it touches moves the *right* way. ADR-0024
established that "not implemented" and "answered wrongly" must stay different
facts, and that remains correct — but it makes `measured=False` a load-bearing
signal, and nothing was checking that the cases carrying it deserved it.

## The correction to ADR-0051

ADR-0051 reported `containing_evidence_recall_at_10` rising 0.9824 → 0.9941 on
re-typing q006, and attributed it to the lexical channel answering the question
where `TRACE_FLOW` structurally could not.

**The conclusion was right and the verification did not establish it.** With
`CONCEPTUAL` measured, the figure is **0.9943** — q006 genuinely does pass
evidence containment through the lexical channel, exactly as argued. But the
number ADR-0051 quoted was obtained with q006 **not measured at all**, so at the
time it was reported it was denominator movement wearing a diagnosis's clothes.

That distinction is the whole point of this record. A conclusion that happens to
be true, verified by a measurement that could not have shown it, is indis-
tinguishable from a wrong one until someone checks. **ADR-0051's reasoning
stands; its evidence is replaced by the numbers below.**

## Decision

**`CONCEPTUAL` joins `SUPPORTED_INTENTS`, and a corpus-derived guard enforces
that every intent used on a measurable fixture is itself measurable.**

`CONCEPTUAL` is deliberately **not** added to `LEXICAL_INTENTS`. ADR-0023 scopes
`lexical_resolution` to configuration and document lookups, where "did the right
thing rank first" is the question posed; a conceptual question is not top-1
shaped. So it is answered through the same lexical channel, measured on recall
and evidence, and scored by neither top-1 metric — which is where ADR-0023 put
`CONCEPTUAL` and `POLICY` in the first place.

`POLICY` stays out. Its only case, q038, sits on `malicious_unsupported` and is
excluded by fixture regardless; the guard is scoped to supported fixtures so it
does not demand support for something deliberately out of scope.

## Consequences

Four metrics fall. **They fall to the truth**, and `unmet_targets` is unchanged
at `['changed_symbol_precision']` — no gate breaks.

| Metric | Reported | Measured | Cause |
| --- | ---: | ---: | --- |
| `relation_path_recall` | 0.9130 | **0.8750** | q024 emits no relation paths |
| `relation_path_correctness` | 0.8261 | 0.7917 | same |
| `primary_evidence_recall_at_10` | 0.9471 | 0.9310 | q024 |
| `exact_evidence_rate` / `valid_evidence_rate` | 0.6880 | 0.6591 | q024 |
| `ndcg_at_10` | 0.9145 | 0.9109 | q024 |
| `symbol_recall_at_10` | 0.8879 | 0.8833 | q024 |
| `containing_evidence_recall_at_10` | 0.9941 | 0.9943 | q006, measured, passes |
| `exact_symbol_resolution` | 1.0000 | **1.0000** | unchanged — neither case is symbol-shaped |

`abstention_correctness`, `mean_reciprocal_rank` and every change-side metric are
unchanged. `baseline-phase-7` and `rerank-phase-7` reproduce byte-for-byte:
`predict_conceptual` is a separate path and does not read this constant.

**Every number this record lowers was previously quoted in a handoff, a register
row, or `extra_build.md`.** They are corrected there rather than left to
disagree, because a stale figure that flatters is worse than one that is merely
old.

### It grows Task 4

q024 is a **third** case blocked by the cause ADR-0034 left open — a lexical
answer emitting no relation paths, here `Sample Service DOCUMENTS service.port`.
Task 4 was scoped as q027 and q029; it is three cases, and `relation_path_recall`
is 0.8750 rather than 0.9130. The ruling that blocks it is unchanged.

### The guard

`test_every_intent_on_a_measurable_fixture_is_itself_measurable` derives its
expectation from the **corpus**, never from the constant — ADR-0017's central
lesson, which the neighbouring assertion still violates by construction:
`set(SUPPORTED_INTENTS) == SYMBOL_INTENTS | LEXICAL_INTENTS` compares three
constants and agrees with itself whatever the corpus contains. That assertion is
kept, and narrowed to state the containment it actually means.

Mutation-checked two ways: reverting the constant to its stale value fails the
guard, and renaming a corpus case's intent to one nothing supports fails it by
name. The second matters more — it is the case the guard exists for, a *future*
intent, and it is the one a test written against today's corpus would miss.
