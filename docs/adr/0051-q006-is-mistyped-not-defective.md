# ADR-0051: q006's intent is wrong, not its engine

- Status: accepted
- Date: 2026-08-16
- Decision owners: user/product (ruling given 2026-08-16) and implementing agent
- Supersedes: none
- Related: ADR-0047 (graph evidence is the reference site), ADR-0023 (target
  profiles and metric scope), ADR-0033 (threshold granularity), ADR-0050 (q035),
  ADR-0003 (the corpus is never edited to move a number), ADR-0024 (unmeasured
  is not wrong)

## Context

q006 was carried as **the only candidate *engine* finding this project had
produced in nine investigations**. `documentation/extra_build.md` framed it as:

> The claim is "duplicate keys are handled"; the line that proves it is
> `return "duplicate"` (`idempotency.py:7`). **The engine cites line 8**,
> `self._keys.add(key)` … `claim` has no outgoing resolved relation, so the
> trace has no edge to cite and the evidence is falling back to something else —
> plausibly a chunk or lexical hit.

It was flagged as the case where the standing "instrument, not engine" prior —
by then confirmed eight times — would most likely bury a real defect. It was
therefore investigated on the assumption it might be one.

## What the investigation found

**Both halves of the stated hypothesis are false.**

`IdempotencyStore.claim` has exactly **one** outgoing edge: `CALLS add` at
**line 8**, `self._keys.add(key)`, unresolved because `add` is a builtin set
method. So the trace does have an edge, and there is no fallback: `_respond`
builds one `EvidenceCandidate` per edge directly from `edge.start_line` /
`edge.end_line` (`application/graph_queries.py:305-318`). No chunk and no
lexical result participates. **Line 8 is cited because the edge is at line 8.**

**The framing "cites a line that does not prove the claim" is also wrong.** The
claim the engine makes is

> `IdempotencyStore.claim calls add at src/payments/idempotency.py:8.`

and line 8 is `self._keys.add(key)`, which proves precisely that. The cited line
proves the claim it makes. What it does not do is *answer the question*, and
those are different failures. `AGENTS.md` §4.1 requires evidence to support the
claim; it is not violated here.

**Line 7 is structurally unreachable by this intent.** `return "duplicate"`
contains no relation. A `TRACE_FLOW` follows edges, and under ADR-0047 a graph
answer's evidence *is* a reference site. There is no edge at line 7 and there
never could be, so no correct trace can cite it.

**The product does not route this question to a trace.** Its deterministic
classifier (`conversations/intent.py`) resolves the question as `text`:

| Question | Corpus declares | `classify()` returns |
| --- | --- | --- |
| "How are duplicate keys handled?" (q006) | `TRACE_FLOW` | `text` |
| "What validates the capture key?" (q003) | `TRACE_FLOW` | `text` |
| "What does strict mode do?" (q035) | `TRACE_FLOW` | `text` |

The harness bypasses the classifier by design and obeys the declared intent —
`_query_term`'s docstring is explicit that it "measures resolution accuracy …
not question understanding". That scoping is deliberate and is not challenged
here. But it means **a declared intent that no classifier would produce is never
cross-checked**, and q006's is one.

## Decision

**q006 is mis-typed. Its intent becomes `CONCEPTUAL`, and one scored
symbol-intent case is added in the same change to hold the denominator.**

The lexical channel — the one the product would actually use — returns
`idempotency.py:5-9`, the `claim` method, which **contains** line 7. So the
expectation is satisfiable, by the channel the question belongs to, with **no
engine change and no change to `expected_evidence`**. That is the evidence for
the diagnosis: the case fails under one intent and passes under another while
everything else is held fixed.

**The compensating case is not optional, and this is the trap worth recording.**
`TRACE_FLOW` is in `SYMBOL_INTENTS`, so re-typing q006 removes it from
`exact_symbol_resolution`'s denominator — **50 → 49**. At 49, one miss scores
**0.9796 and fails the 0.98 gate**; at 50 it scores 0.9800 and passes. This is
ADR-0033's granularity argument exactly, and the corpus sits precisely on the
boundary. Re-typing alone would have spent the margin ADR-0050 restored hours
earlier.

**q064** therefore joins the corpus: `Where is OrderPipeline declared?`,
`EXACT_SYMBOL`, over `symbol_breadth`. It is a genuine coverage gap rather than
padding — `OrderPipeline` is that fixture's central class and appears in the
corpus only as `OrderPipeline.advance` (q047, q053, q055); the class itself was
never a subject or an expected answer. Its range, `pipeline.py:17-24`, is
derived from the source and matches the sibling convention (`OrderRepository`
14-24).

## Consequences

| Metric | Before | After | Note |
| --- | ---: | ---: | --- |
| `exact_symbol_resolution` | 1.0000 (/50) | 1.0000 (**/50**) | gate 0.98; **margin held** |
| `containing_evidence_recall_at_10` | 0.9824 | **0.9941** | gated at 0.90 |
| `primary_evidence_recall_at_10` | 0.9353 | 0.9471 | gated at 0.90 |
| `containing_evidence_rate` | 0.7520 | 0.7600 | ungated (ADR-0048) |
| `exact_evidence_rate` / `valid_evidence_rate` | 0.6800 | 0.6880 | ungated |

`unmet_targets` remains `['changed_symbol_precision']`. No change-side metric
moved. No source file changed.

**This is the ninth consecutive investigation to end at the instrument rather
than the engine**, and the prior was not applied as a reflex to get there: the
engine's actual claim text was read against the lines it cites, the evidence
construction was traced to its source, and the product's classifier was run,
before the conclusion was reached.

### Three ways a case can score without measuring what it claims

All three were found by mutation on 2026-08-16, and they are recorded together
because they are one family — **the metric that passes is not always the metric
the case is about.**

1. **Whole-file evidence satisfies any line in that file.** Moving q006's
   expected line from 7 to 1 was **not detected**. For the harness's query term
   the lexical channel returns *two* items, and the second is
   `idempotency.py:1-9` — a module-level chunk containing every line. q006's
   credit for line 7 is legitimate (the method chunk `5-9` contains it), but the
   case cannot detect a *wrong* line.
2. **`exact_symbol_resolution` cannot detect a wrong expectation.** Changing
   q064's `expected_symbols` to a different real symbol still scored 1.0,
   because `_query_term` feeds `expected_symbols[0]` in as the query and then
   checks it comes back. The metric asks "does the named symbol resolve", not
   "is the named symbol right". Documented in the docstring; the consequence was
   not. The evidence metric is what caught it.
3. **No name-based metric separates two same-named symbols** — ADR-0050.

q064 was mutation-checked against the metric that must move: pointing its
evidence at the wrong lines, and naming a different symbol, each drop
`containing_evidence_recall_at_10` 0.9941 → 0.9824.

**q064 is not ranking-sensitive**, and that is stated rather than implied. It
returns a single symbol, so a ranking reversal is a no-op for it, exactly like
the 23 cases added 2026-08-15. The open register row on ranking sensitivity is
**not** discharged by this change, and the reason it could not be discharged
here is itself worth recording: a case is only ranking-sensitive when the engine
returns at least one symbol *outside* `expected_symbols`, and for graph intents
the corpus declares every edge endpoint, so a reversal cannot change the top-1
verdict. That is a fixture-shaped problem, which is Task 6's scope.

### Deliberately not done

- **Expecting line 8.** It would fit the engine's output and assert something
  false — `self._keys.add(key)` records a key, it does not handle a duplicate.
- **Changing the engine so a trace also cites the traced symbol's definition.**
  It contradicts ADR-0047, which was ruled the same day, and would move many
  numbers to fix one mislabelled case.
- **Re-typing q003 and q035 to match.** Both carry `TRACE_FLOW` and both
  classify as `text`, so the mislabel may be systemic across the six
  `TRACE_FLOW` cases. They are **left alone and recorded**: q035 was just
  settled by ADR-0050 and reopening it the same day on a different axis would
  discard that evidence, and q003 currently passes. A systemic audit is its own
  task, listed in the Deferred Register.
