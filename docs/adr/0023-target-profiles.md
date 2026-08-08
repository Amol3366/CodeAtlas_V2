# ADR-0023: A Corpus Declares Which Instrument Measures It

- Status: accepted
- Date: 2026-08-09
- Decision owners: user (three explicit rulings), implementing agent (record)
- Supersedes: none
- Extends: ADR-0003 (which evidence rate a claim names)

## Context

`_unmet_targets` applied **one target table to every dataset**. The table was
written for the Phase 0 corpus — 40 mixed-intent cases about resolving symbols —
and was then applied unchanged to the Phase 7 semantic corpus, 14 deliberately
fuzzy conceptual questions whose expected answers are sometimes document
headings rather than code symbols.

Two of the resulting "unmet targets" were carried in `documentation/memory.md`
for months and read as engine defects.

`exact_symbol_resolution` was also scored over **every** case with expected
symbols regardless of intent, despite a name and a 0.98 target that describe
exact symbol lookup. Decomposing it on the main corpus:

| Intent group | Top-1 | Rate |
| --- | --- | ---: |
| `EXACT_SYMBOL` | 15/15 | **1.0000** |
| Graph (`CALLERS`, `DEPENDENCIES`, `EXPORTS`, `RELATED_TESTS`, `TRACE_FLOW`) | 12/12 | **1.0000** |
| `CONFIG_LOOKUP` | 1/6 | 0.1667 |
| `DOCUMENT_LOOKUP` | 2/4 | 0.5000 |
| `CONCEPTUAL` / `POLICY` (force-abstained by the intent gate) | 0/2 | 0.0000 |

The engine is perfect on every symbol-shaped question. The 0.7692 aggregate was
produced entirely by lexical lookups, where "did the right *symbol* rank first"
asks something other than what was posed — a config-key question is answered by
matching text.

Finally, `valid_evidence_rate >= 1.0` gated on **exact span equality**, and
ADR-0003 already records why that is the wrong measure: graph answers cite every
supporting edge, so a call-site line rarely equals a gold range describing a
definition. The gate was failing on a granularity disagreement, not on validity.

## Decision

**1. `exact_symbol_resolution` covers symbol-shaped intents only, and a new
`lexical_resolution` gates the rest.** Scoping a metric until it reads 1.0000 is
exactly how a number gets gamed, so the lexical gate is **not optional** — it is
the condition on which the scoping is honest. It currently reads **0.3000
against 0.90 and fails.**

**2. A dataset declares a `target_profile`.** `retrieval` is the default, so
every existing manifest stays valid unchanged; `semantic_cases` declares
`conceptual`. The conceptual profile drops `exact_symbol_resolution` and
`lexical_resolution` — top-1 is the wrong instrument for a fuzzy question — and
gates `symbol_recall_at_10` instead: did the right answer surface at all.

**3. The evidence gate reads `containing_evidence_rate`, and the threshold stays
1.0.** "All evidence must be valid" is unchanged as a demand; only the
definition of *valid* is corrected. Nothing was relaxed — inventing a lower
number would have been the quiet relaxation. `exact_evidence_rate` is still
reported beside it, because the gap between the two rates is itself the
measurement (ADR-0003).

**4. The intent vocabulary lives in `dataset.py`,** with the corpus contract, and
`engine_adapter` imports it. Two definitions of one set is how the `--format pr`
defect happened; a test asserts `GRAPH_INTENTS ⊆ SYMBOL_INTENTS` and that
`SUPPORTED_INTENTS` is exactly the union.

The `lexical_resolution` threshold of 0.90 is **provisional**, chosen to match
the existing recall family (`primary_evidence_recall_at_10`,
`direct_impact_recall`) rather than picked for the number it produces. It is the
one figure here not derived from an existing decision, and it is open to revision.

## Consequences

Main corpus (`retrieval` profile):

| Metric | Before | After |
| --- | ---: | ---: |
| `exact_symbol_resolution` | 0.7692 / 0.98 unmet | **1.0000 / 0.98 met** |
| `lexical_resolution` | — | **0.3000 / 0.90 unmet (new)** |
| evidence gate | `valid_evidence_rate` 0.6316 / 1.0 | `containing_evidence_rate` 0.6974 / 1.0 |

Phase 7 (`conceptual` profile) goes from four unmet targets to **two**:
`primary_evidence_recall_at_10` (0.6667) and `symbol_recall_at_10` (0.7857).
`exact_symbol_resolution` reports **not applicable** — that corpus has no
symbol-shaped case, so the metric is not computed rather than scored as zero.

**The unmet count fell, and that is not the point.** Nothing about the engine
improved in this record. Three numbers stopped being measured by instruments
built for a different question; one new gate was added and fails honestly.

### The semantic uplift record

`exact_symbol_resolution` was one of the metrics `run_phase7_baseline.py`
compared, and it now reports `not applicable` on both sides. `symbol_recall_at_10`
was added beside it and carries the same signal for this corpus — **0.7143 →
0.7857, +0.0714**, the identical uplift magnitude the old row reported. The
Phase 7 admission record is therefore unchanged in substance.

### A test was changed, and why that is not weakening one

`test_rerank_ab_records_a_decline_against_the_semantic_baseline` asserted every
delta equalled `0.0`, proving reranking moved nothing. A metric that no longer
applies reports a `None` delta, which is also "not moved". The assertion now
rejects any non-zero delta **and** requires at least one metric to have actually
been compared, so it cannot pass vacuously if everything became inapplicable.

### Still open

Whether `lexical_resolution >= 0.90` is the right bar, and whether
`containing_evidence_rate >= 1.0` is reachable or should be argued down with
evidence rather than convenience. Both are thresholds; neither changes what is
being measured.
