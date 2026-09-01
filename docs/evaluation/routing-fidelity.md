# Routing fidelity: what the corpus scores when the classifier picks the channel

Measured 2026-09-02 by `scripts/report_routing_fidelity.py` (RW-02). Raw output
in `routing-fidelity.txt`.

## The number

**63 of 80 query cases change channel, and all 63 go to the same place** — the
lexical fall-through (`TEXT`, scored as `CONCEPTUAL`). **Zero** cases route to a
*different* structured channel, and zero are unroutable.

| Declared intent | Falls through | Keeps its channel |
| --- | ---: | ---: |
| `EXACT_SYMBOL` | 36 | 0 |
| `CONFIG_LOOKUP` | 6 | 0 |
| `DEPENDENCIES` | 5 | 5 |
| `CALLERS` | 4 | 6 |
| `TRACE_FLOW` | 4 | 1 |
| `DOCUMENT_LOOKUP` | 4 | 0 |
| `EXPORTS` | 3 | 0 |
| `POLICY` | 1 | 0 |
| `RELATED_TESTS` | 0 | 3 |
| `CONCEPTUAL` | 0 | 2 |

**This independently reproduces DR-09's audit.** That audit reported
`EXACT_SYMBOL` agreeing on 0 of 36 and `TRACE_FLOW` on 1 of 5, using a different
tool and a different question. The two agree exactly, which is the cross-check
neither had alone.

## What it costs, which DR-09 could not show

Agreement was a count. This is the consequence:

| Metric | Declared | Routed |
| --- | ---: | ---: |
| `relation_path_recall` | **1.0** | **0.8743** |
| `relation_path_correctness` | 0.9024 | 0.5857 |
| `exact_evidence_rate` | 0.6404 | 0.2369 |
| `containing_evidence_rate` | 0.7544 | 0.5100 |
| `mean_reciprocal_rank` | 1.0 | 0.8985 |
| `symbol_recall_at_10` | 0.9013 | 0.8333 |
| `abstention_correctness` | 1.0 | 0.9868 |
| `lexical_resolution` | 1.0 | **None** |

Two are worth naming. `relation_path_recall` is gated **absolutely at 1.0**
(ADR-0058), so a routed corpus fails that gate. And `lexical_resolution` goes
**undefined**, not down: routed, no case remains on `CONFIG_LOOKUP` or
`DOCUMENT_LOOKUP` at all, so the metric loses its denominator entirely.

## The caveat, which is not small

**This is not a user-facing failure rate, and must not be quoted as one.**

Corpus questions were authored as natural-language probes for a harness that
feeds the declared symbol and bypasses the classifier — `_query_term` says so.
They were never written to be typed at a classifier whose rules are
command-shaped (`who calls X`, `dependencies of Y`). So 63 of 80 measures
**corpus-question style against classifier-rule shape**, which is a real
mismatch but not evidence that 79% of user questions misroute.

What it does establish is a floor: for these phrasings, the structured channels
the corpus measures are unreachable.

## For the ruling

The register row asks whether to widen the `TRACE` rule.

**Widening trace alone reaches 4 of the 63.** The property is general — *every*
rule in `_RULES` is anchored at both ends and admits one trailing subject token,
so `Where is PaymentService defined?` misses for the same structural reason
`Trace order data from frontend to backend.` does. Trace is where it was
noticed, not where it lives.

Three options, stated without choosing:

1. **Leave the classifier; record the finding.** The corpus keeps measuring
   channels directly, which is what it was built for, and routing stays
   unmeasured in the gate.
2. **Widen the trace rule only.** Closes the row as written, moves ~4 cases, and
   leaves the general shape untouched — the next phrasing report reopens it.
3. **Treat routing as its own instrument and set a target.** Requires deciding
   what corpus is legitimate for it: the query corpus is the wrong sample, since
   its questions were written for a harness that never routes.

Option 3 is the only one that makes the number above a gate rather than a note,
and it needs a corpus that does not exist yet. That cost is stated here rather
than discovered later.
