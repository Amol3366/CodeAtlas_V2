# ADR-0050: q035 declares its subject, and its evidence is the reference site

- Status: accepted
- Date: 2026-08-16
- Decision owners: user/product (ruling given 2026-08-16) and implementing agent
- Supersedes: none
- Related: ADR-0047 (graph evidence is the reference site), ADR-0018 (graph cases
  declare their subject), ADR-0003 (the corpus is never edited to move a number),
  ADR-0031 / ADR-0036 (when an expectation may be corrected), ADR-0048
  (`containing_evidence_rate` is reported, not gated)

## Context

`exact_symbol_resolution` stood at **49/50 = 0.9800 against a 0.98 target** —
exactly on the line, with no margin. One more miss anywhere would have given
0.9600 and failed a release gate. q035 was the single miss.

The cause was ADR-0047's neighbouring ruling. Re-including `git_changes/target/`
so q034 could be answered put a **second symbol named `process`** into the
fixture index: `base/service.py:1` and `target/processor.py:1` both define one.
q035 asks "What does strict mode do?", the harness fed `expected_symbols[0]` —
the bare name `process` — as the trace subject, `find_exact` returned two roots,
and `GraphQueryService._answer` abstained with `SYMBOL_AMBIGUOUS`.

**The abstention is correct behaviour.** `AGENTS.md` §4.1 prefers abstention to
guessing, and answering for one of two candidates would silently substitute a
question the caller did not ask. The defect was in the expectation, which named
a symbol that exists twice with no way to say which.

## Finding 1 — the stated blocker was wrong

`documentation/extra_build.md` recorded that a disambiguating `query_subject`
"may not be expressible", because "`find_exact` resolves by name and there is no
file-scoped selector".

**There is one.** `SymbolStore.find_exact` (`storage/sqlite/stores.py:463`) tries
four tiers in order, and tier 2 is `module_path || '.' || qualified_name`.
Probed against a real index of the fixture:

| Selector | Roots |
| --- | ---: |
| `process` | 2 — ambiguous |
| `target.processor.process` | **1** |
| `base.service.process` | **1** |
| `processor.process` | 0 |

The belief was never tested against the store. It is recorded here because the
plan carried it as a constraint on the option set, and it removed the cheapest
option from consideration.

**Why nobody found it sooner: the ambiguity message does not disambiguate.** The
abstention reads

> `'process'` is ambiguous in the active snapshot and matches 2 symbols:
> process, process. Ask again with a qualified name.

It lists `qualified_name`, which is *identical* for both candidates. A caller
told to ask again with a qualified name is shown two identical names and given
no usable next step. The field that separates them — `module_path` — is the one
tier 2 already accepts. This is a real usability defect in a live error path,
not only an evaluation artefact; it is recorded in the Deferred Register rather
than fixed here, because it is an engine change and this record is a corpus
ruling.

## Finding 2 — the case was not measuring what it claimed

Declaring `query_subject: "target.processor.process"` restores the margin. It was
then **mutation-checked by pointing the subject at the wrong side**,
`base.service.process` — and the mutation was **not detected**: every metric
scored identically.

The reason is that `expected_symbols` is `["process"]` and *both* sides define a
symbol of that name, so `exact_symbol_resolved`, `mean_reciprocal_rank` and
`abstention_correctness` — all of which read the symbol's name — cannot tell the
two traces apart. q035 would have passed while tracing the wrong file.

This is the same shape as the open register row recording that the 23 cases added
2026-08-15 are not ranking-sensitive: **corpus growth and corpus repair both
raise a count without necessarily raising coverage.** A fix that restores a
number without restoring discrimination is worth less than it looks, and only the
mutation-check separated the two.

## Decision

Two corrections to q035, ruled together and recorded separately because they rest
on different authorities.

**1. q035 declares `query_subject: "target.processor.process"`.**

This is additive and is not a re-labelling. `QueryCase.query_subject` exists for
exactly this and its own comment states the rule: *"declaring it is additive,
never a re-labelling of an expectation (ADR-0003)"*. The subject is derived from
the case, not from the engine — q035's own `expected_evidence` already names
`target/processor.py`, and `base/` has no `strict` parameter, so the target side
is the only side the question can be about. `expected_symbols` is unchanged.

**2. q035's `expected_evidence` becomes `target/processor.py:4-4`.**

This applies **ADR-0047's existing ruling** as a ninth instance. q035 declared
the whole definition range `1-5` where the engine cites the reference site; it
could not be among the eight corrected on 2026-08-16 because it was abstaining
and emitted nothing to compare against. Line 4 is
`raise ValueError("value is required")` — the line that proves what strict mode
does, and the claim the engine makes is *"process calls ValueError at
target/processor.py:4."*

**The fitting risk is stated rather than waved away.** `extra_build.md`'s
governing rule is to derive an expectation from the claim and never from the
engine's output, and this expectation does coincide with the engine's output. The
justification is that the convention was ruled on **2026-08-16, before q035
emitted anything at all** — so this applies a prior rule to a case that had been
invisible to it, rather than reading a number off a run and blessing it. Had the
convention not already existed, this correction would have required its own
argument.

`_contains`, the engine, the metric definitions and every other case are
untouched.

## Consequences

Measured on the main corpus, control run first confirmed byte-identical to the
tracked `baseline-phase-4.json`:

| Metric | Before | After | Note |
| --- | ---: | ---: | --- |
| `exact_symbol_resolution` | 0.9800 | **1.0000** | 50/50; the gate has margin again |
| `abstention_correctness` | 0.9828 | 1.0000 | ungated |
| `mean_reciprocal_rank` | 0.9828 | 1.0000 | ungated |
| `containing_evidence_recall_at_10` | 0.9706 | **0.9824** | gated at 0.90 |
| `primary_evidence_recall_at_10` | 0.9235 | 0.9353 | gated at 0.90 |
| `containing_evidence_rate` | 0.7561 | 0.7520 | ungated (ADR-0048) |
| `symbol_recall_at_10` | 0.8707 | 0.8879 | ungated on this profile (ADR-0023) |
| `ndcg_at_10` | 0.8973 | 0.9145 | ungated |

`changed_symbol_precision` (0.9464, structural, ADR-0003) remains the only unmet
target, unchanged. No change-side metric moved.

- **The gate margin is restored.** `exact_symbol_resolution` at 1.0000 tolerates
  one future miss at 0.9800 and still passes. It should not be quoted as
  headroom beyond that: at 50 cases, 0.98 permits exactly one miss, which is the
  granularity ADR-0033 predicted and no more.
- **The case now discriminates.** Re-running the wrong-side mutation with both
  corrections applied **is** detected: `containing_evidence_recall_at_10` falls
  0.9824 → 0.9706 and `containing_evidence_rate` 0.7520 → 0.7500. Correction 2
  is what supplies that, because the two sides' reference sites are in different
  files while their symbol names are identical. Correction 1 alone restores the
  number without restoring the measurement.
- **`containing_evidence_rate` falls, and that is expected.** An answering case
  emits evidence a previously-abstaining one did not. It is reported and not
  gated (ADR-0048), so this is noted rather than avoided.
- **ADR-0047 carries a dangling forward reference.** Its line 39 cites
  "ADR-0049" for the `target/` ignore collision, and no ADR-0049 exists — the
  Ruling 2 fix landed as a fixture-local `.codeatlasignore` without one. This
  record therefore takes **0050**, leaving 0049 free for the record ADR-0047
  already promised. Recorded in the Deferred Register.
