# ADR-0026: An Exact Name Match Outranks a Lexical One

- Status: accepted
- Date: 2026-08-09
- Decision owners: user (asked for the ranking defect next), implementing agent (record)
- Supersedes: none
- Extends: ADR-0025 (which exposed this by making nested keys addressable)

## Context

ADR-0025 made nested configuration keys addressable symbols, and
`lexical_resolution` rose 0.3750 → 0.6250. It was predicted to reach 0.8750, and
did not. Two cases still failed, and probing the index showed the symbols
existed — so the remaining defect was not extraction.

`search_chunks` ordered results by `bm25(chunk_search)` and nothing else. BM25
scores by term density, so:

```
search 'features.audit' -> ['features', 'features.audit', ...]   parent first
search 'service.port'   -> ['service.port', 'service', ...]      leaf first
```

`features:` is a two-line block; `service:` is three lines plus a name. The
shorter parent out-scored the leaf its caller had asked for by name, and the
longer one did not. **Whether a caller got the key they asked for or its parent
depended on how many other lines the parent happened to contain** — not a
property anyone should be relying on, and not one any caller could predict.

## Decision

**Promote a chunk whose `qualified_name` *is* the query, ahead of BM25 order.**
Asking for a name by name is the least ambiguous signal a caller can send, and
it should not lose to a scoring accident.

**It lives in the retrieval service, not the SQL.** Ranking policy belongs in
`LexicalSearch`; FTS syntax stays in the store, which is the separation
`search_chunks`' own docstring argues for when it refuses to accept a column
name it did not choose.

Two bounds are stated in the code rather than left implicit:

- **It reorders within the window the query already returned.** `limit` is
  applied by SQL, so an exact match ranked below the cutoff never arrives to be
  promoted. This is *not* a guarantee that an exact match always wins, and it
  must not be described as one.
- **It is a stable partition.** Every non-exact hit keeps its relative BM25
  order, so a query with no exact match is returned exactly as before. A test
  pins that: without it, this would be a general retrieval change wearing a bug
  fix's clothes.

### It breaks a documented invariant, deliberately

`search_text`'s docstring records that the relaxed-fallback design was chosen so
that "a query that finds results today finds exactly the same results after this
change… it is the property to preserve if this is ever reworked."

That property is preserved for *membership* — the same chunks match — but not
for *order*, which this record changes on purpose. It is called out here rather
than silently amended, because the original note exists to make a future author
think before reordering, and thinking about it is exactly what happened.

## Consequences

| Metric | ADR-0025 | Now |
| --- | ---: | ---: |
| `lexical_resolution` | 0.6250 | **0.8750** (7/8) |
| `mean_reciprocal_rank` | 0.9429 | 0.9714 |
| `ndcg_at_10` | 0.8840 | 0.9051 |
| `exact` / `containing_evidence_rate` | 0.5647 / 0.6588 | unchanged |

The evidence rates not moving is the correct signature for a pure reorder: the
same evidence, returned in a better order.

Across the three commits of this work `lexical_resolution` went
**0.3000 → 0.3750 → 0.6250 → 0.8750**, each step with one attributable cause —
an honest denominator (ADR-0024), extraction (ADR-0025), ranking (here).

### The one remaining failure is not an engine defect

q019 expects `README.Health` while extraction emits the bare `Health`; q027 and
q031 expect a bare `Order flow` and pass. **The corpus uses two naming
conventions for document sections.** That needs a ruling on which convention is
correct, and the expectations must not be edited to move a number (ADR-0003).

### `lexical_resolution`'s threshold is now settable

It was set at 0.90 in ADR-0023 and flagged provisional. With eight scorable
cases every value is a multiple of 0.125, so 0.90 means "8 of 8" and can express
nothing else. The metric now sits at 0.8750 with a single failure whose cause is
a corpus inconsistency rather than engine behaviour. Setting the threshold
should follow the q019 ruling, from this per-case evidence, rather than being
guessed a third time.
