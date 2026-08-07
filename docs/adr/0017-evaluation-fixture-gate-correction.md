# ADR-0017: The Evaluation Fixture Gate Understated the Engine

- Status: accepted
- Date: 2026-08-08
- Decision owners: user (chose to regenerate the tracked baselines), implementing agent (record)
- Supersedes: none
- Extends: ADR-0003 (evidence granularity and the "do not edit the corpus" rule)

## Context

`exact_symbol_resolution` sat at 0.3846 against a 0.98 target for four phases
and was carried in `documentation/memory.md` as the largest open gap on the
board — the metric a future session was told to start with.

It was not an engine gap. `predict_exact_symbols`
(`src/codeatlas/evaluation/engine_adapter.py`) gates cases out of the
measurement by repository fixture:

```python
SUPPORTED_FIXTURES = ("python_app", "docs_config", "mixed_app")
```

A gated case is answered with `_abstention(case)`. That matters because of how
the metric is scored: `exact_symbol_resolved` is `None` — and therefore
excluded from the mean — only when a case has *no* expected symbols
(`runner.py:270`). A forced abstention on a case that *does* have expected
symbols scores `False`. It lands in the denominator as a miss, indistinguishable
from the engine getting the answer wrong.

That tuple was introduced in `b2ea98e`, the Phase 1 commit, and never revisited.
The constant directly above it, `SUPPORTED_INTENTS`, *was* maintained — it
carries comments recording its Phase 2 and Phase 3 widenings. So the intent gate
tracked the engine's capability and the fixture gate did not, while both fed the
same scoring path.

The result: 16 of 39 scored query cases never reached the engine. `tsjs_app` was
excluded although TypeScript/JavaScript parsing shipped in **Phase 3**, and
`git_changes` although Git shipped in **Phase 4**.

The suite could not see this. `test_unsupported_intents_abstain_rather_than_guess`
builds its own expectation by reading `SUPPORTED_FIXTURES`, so it passes for any
value of that tuple, including a stale one.

Measured by re-running the corpus with the gate widened — nine of the twelve
previously-excluded scored cases resolve their expected symbol top-1, first try:

| Metric | Gated | Widened | Δ |
| --- | ---: | ---: | ---: |
| `exact_symbol_resolution` | 0.3846 | 0.6154 | +0.2308 |
| `mean_reciprocal_rank` | 0.3846 | 0.6154 | +0.2308 |
| `abstention_correctness` | 0.5250 | 0.7500 | +0.2250 |
| `symbol_recall_at_10` | 0.3718 | 0.5897 | +0.2179 |
| `primary_evidence_recall_at_10` | 0.5556 | 0.6508 | +0.0952 |
| `changed_symbol_precision` / `changed_symbol_recall` / `direct_impact_recall` / `finding_precision` | unchanged | unchanged | 0.0000 |

The `abstention_correctness` movement is the serious one. The harness was
recording *incorrect abstentions* — CodeAtlas was being reported as declining to
answer questions it answers correctly. For a product whose central claim is that
abstention is a deliberate, trustworthy behavior, a baseline that overstates
abstention by 0.225 misrepresents the thing the product is for.

## Decision

**1. Widen `SUPPORTED_FIXTURES` to every corpus fixture except
`malicious_unsupported`.**

That one stays excluded deliberately, not by neglect. It carries
prompt-injection text; what the engine *should* return for hostile input is a
security question, and letting an accuracy corpus answer it by side effect would
be the same category error this ADR is correcting.

**2. Regenerate `baseline-phase-3` and `baseline-phase-4` only.**

These are the two the live gates re-check byte-for-byte
(`check_phase4.ps1`), so they are assertions about the *current* engine and must
move when the measurement is corrected.

`baseline-phase-1` and `baseline-phase-2` are **not** regenerated. Their gate
scripts are marked `SUPERSEDED` and document that re-running them exits 5 by
design, because those artifacts record what the Phase 1 and Phase 2 engines did.
Regenerating them would overwrite history with today's engine — which
`documentation/rules.md` forbids, and which would destroy the only record of
what those gates were approved against.

**3. Do not edit the corpus.** ADR-0003's rule holds. No case was added,
removed, or reworded; the fixtures, queries, and expected symbols are untouched.
The numbers moved because the harness stopped discarding answers, not because
the questions got easier.

**4. Guard the gate with a test derived from the corpus, not from the
constant.** `test_every_corpus_fixture_is_measured_unless_deliberately_unsupported`
asserts that the corpus fixtures minus `malicious_unsupported` equal
`SUPPORTED_FIXTURES`, so a fixture added later forces an explicit decision
instead of silently scoring zero.

## Consequences

A tracked baseline moved, which the project treats as a significant act. The
byte-for-byte `--check` is what makes that act visible, and it worked as
intended: the check failed (exit 5) before regeneration and passes after.

**The target is still unmet: 0.6154 against 0.98.** This corrects a measurement
error; it does not close the gap, and no one should cite it as though it did.

The correction also exposes the real engine finding that the fixture gate was
hiding — the TypeScript/JavaScript **graph** intents still abstain:

- `q015` `DEPENDENCIES` / `tsjs_app`
- `q016` `CALLERS` / `tsjs_app`
- `q017` `EXPORTS` / `tsjs_app`

TS/JS symbols resolve; TS/JS relation queries do not. That is now the largest
identified contributor to the remaining gap, and it is a genuine capability
question rather than a harness one. It is recorded as open work, not fixed here:
this change is a measurement correction, and bundling an engine change into it
would make the moved baseline impossible to attribute.

**The general lesson.** A test that derives its expectation from the constant it
is testing cannot detect that the constant is wrong. Both the metric and its
guard read `SUPPORTED_FIXTURES`, so the two agreed with each other for four
phases while disagreeing with the engine. This is the same shape as the
`--format pr` defect (a guard each adapter held its own copy of) and the
`GapReason` defect (a capability shipped to one surface): the assertion and the
thing asserted were never independent.
