# ADR-0057: A lexical answer carries the resolved edges of what it matched

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (ruling given 2026-08-17) and implementing agent
- Supersedes: none — it *discharges* the last of ADR-0034's four causes
- Related: ADR-0034 (trace follows routes, and the four causes), ADR-0020
  (every graph answer carries its relations), ADR-0038 (`relation_path_recall`,
  and precision punishing compliance), ADR-0055 (a route cites the handler it
  reaches), ADR-0027 (containment), ADR-0053 (`CONCEPTUAL` is measurable)

## Context

`relation_path_correctness` averaged **four unrelated causes**, which is why
ADR-0038 could not give it a threshold that meant anything. Three have since
been settled — ADR-0034 (`trace` never traversed `ROUTES_TO`), ADR-0039
(`IMPORTS` targets the bound symbol), ADR-0055 (a route's claim dropped when it
shared a line). This is the fourth.

The declared edges of q024, q027 and q029 **are stored and resolved**. The
answers returned `relation_paths: []` because only the graph intents ever
populated the field. Verified by probe rather than assumed:

| Case | Intent | Subject | Outgoing | Resolved |
| --- | --- | --- | ---: | --- |
| q024 | `CONCEPTUAL` | `Sample Service` | 6 | 1 — `DOCUMENTS service.port` |
| q027 | `DOCUMENT_LOOKUP` | `Order flow` | 10 | 2 — `get_order`, `loadOrder` |
| q029 | `CONFIG_LOOKUP` | `healthPath` | 1 | 1 — `REFERENCES health` |

ADR-0034 named this explicitly as **"a design decision, not a defect to fix
quietly"**, and that decision had never been taken. It is what blocked the work.

It is three cases rather than the two long recorded: **q024 joined only after
ADR-0053** added `CONCEPTUAL` to `SUPPORTED_INTENTS`, before which it was never
measured at all.

## Decision

**A lexical or conceptual answer emits relation paths, restricted to edges that
resolve to a real target.**

The restriction follows ADR-0055, where an unresolved route cites nothing extra,
and it is **structural rather than stylistic**. `RelationRecord` sets
`target_symbol_id` for no state except `RESOLVED`, so an unresolved edge has no
far endpoint and cannot form a path at all. `Order flow` is the demonstration:
**eight of its ten `DOCUMENTS` edges point at ordinary prose words** — "order",
"flow", "requests", "orders", "frontend", "status", "backend", "returns" — that
name no symbol. Emitting those would turn a wording coincidence into an apparent
relationship.

Three properties are decided deliberately and pinned by tests:

- **Claims are untouched.** A lexical hit is evidence of *wording*, not
  behaviour, and stays `high_confidence_heuristic`. The contract keeps
  `answer.claims` and `relation_paths` in separate fields with their own
  derivations, which is the only reason this is expressible without upgrading a
  text match into a resolved fact.
- **A step carries the edge's derivation, not the hit's.** How an edge was
  derived and how a chunk was matched are different questions; letting the
  lexical confidence overwrite a resolved edge's would hide that the edge was
  resolved rather than guessed.
- **A step cites evidence the answer already returned** — the chunk whose range
  *contains* the edge's reference site — never a new row. Building fresh
  evidence would enlarge the cited set and move `containing_evidence_rate` as a
  side effect of a field nobody asked to change. A step with no containing chunk
  is withheld, the rule `GraphQueryService._paths` already applies.

`MAX_RELATION_PATHS` bounds one answer at 10 (Section 10.3): a broad query can
match many chunks and a chunk's symbol can carry many edges, so the product is
otherwise unbounded. Paths are ordered by where their evidence ranked, so the
ceiling drops the least relevant matches rather than an arbitrary set.

## Measured

Phase 4 corpus, 64 query cases:

| Metric | Before | After |
| --- | ---: | ---: |
| `relation_path_recall` | 0.8750 | **1.0000** |
| `relation_path_correctness` | 0.7917 | **0.8646** |
| every other metric | — | **unchanged** |

`containing_evidence_rate` holding at 0.7537 is the signature the design aimed
for: no evidence row was added, so the field that would have moved as a side
effect did not.

Five cases changed, verified against the pre-change tree rather than reasoned
about:

| Case | Intent | Declared | Emitted | Precision | Recall |
| --- | --- | ---: | ---: | --- | --- |
| q024 | `CONCEPTUAL` | 1 | 0 → 1 | 0.00 → **1.00** | 0.00 → **1.00** |
| q027 | `DOCUMENT_LOOKUP` | 1 | 0 → 2 | 0.00 → **0.50** | 0.00 → **1.00** |
| q029 | `CONFIG_LOOKUP` | 1 | 0 → 4 | 0.00 → **0.25** | 0.00 → **1.00** |
| q006 | `CONCEPTUAL` | 0 | 0 → 2 | 1.00 → **0.00** | 1.00 → 1.00 |
| q031 | `DOCUMENT_LOOKUP` | 0 | 0 → 2 | 1.00 → **0.00** | 1.00 → 1.00 |

## The prediction that failed, and what it taught

**Precision was predicted to fall and it rose.** The reasoning was that q027
emits two true edges where the corpus declares one, which is ADR-0038's shape
exactly. That much is right — q027 does score 0.50.

The model was wrong about the *baseline*. `_precision` returns **0.0**, not 1.0,
when nothing is predicted and something is expected, so q024, q027 and q029 were
scoring **zero on precision as well as recall** before this change. Emitting
anything that includes the declared edge is therefore a strict improvement, and
the "cost" the plan anticipated never existed.

Both deltas reconcile exactly against a denominator of **24** — the measured
cases that declare a relation:

```
recall       3 cases 0.00 -> 1.00              =  3.00 / 24 = +0.1250   observed +0.1250
correctness  (1.00 + 0.50 + 0.25) - 0.00       =  1.75 / 24 = +0.0729   observed +0.0729
```

## What this hides, stated

**q006 and q031 now emit true edges the corpus does not declare, and the metric
cannot see it.** Their precision falls 1.00 → 0.00, and the aggregate excludes
them: `relation_scores` is built only from cases where
`case.expected_relations` is non-empty. A case that declares nothing cannot
measure relation accuracy, which is defensible — but it means this change made
two answers broader with **no number moving anywhere**, and a future change that
made them broader still would be equally invisible.

This is recorded rather than fixed. Declaring relations on q006 and q031 to make
them visible would be editing the corpus in response to an engine change, which
ADR-0003 forbids.

## Mutation results

Four mutations, and **two could not be exercised** — recorded rather than
counted as coverage, on ADR-0055's precedent.

| Mutation | Caught |
| --- | --- |
| Emit unresolved edges naming `target_hint` — *the rejected design* | **yes**, 2 tests |
| Overwrite a step's derivation with the lexical hit's | **yes**, 1 test |
| Make containment exclusive (`start < line < end`) | **yes**, 3 tests |
| Delete the `target_symbol_id is not None` filter | **no — a no-op** |
| Cite a fabricated id when no chunk contains the edge | **no — unreachable** |

The filter deletion is a no-op because an unresolved edge also fails the label
lookup immediately after, so both guards implement the same rule and removing
one changes nothing. **The mutation that matters is the rejected design**, not
the reverted edit — ADR-0050's lesson, applied deliberately: a mutation that
merely undoes the change teaches nothing.

The fabricated-id branch is unreachable from the corpus fixtures, where every
edge falls inside a returned chunk. `_containing` is therefore pinned by a
direct unit test instead, including both rejection cases the fixtures cannot
produce, and the unexercised branch is a register row.

## Alternatives

**Emit every stored edge** (the strictest reading of ADR-0020). Rejected by the
ruling. Measured while mutation-checking: it fails two tests, and the
`MAX_RELATION_PATHS` ceiling then pushes the declared `get_order` out of q027's
answer entirely — eight prose-word edges crowding out the one true one.

**Emit nothing and correct the three expectations instead.** Rejected: the edges
are real, stored and resolved, and an MCP client asking a documentation question
would keep getting prose with no machine-readable statement of what relates to
what — the exact gap ADR-0020 was written to close.

**Set the `relation_path_recall` gate target now.** Deliberately deferred by the
ruling. ADR-0032 and ADR-0033 are both records of a threshold that was
arithmetically meaningless for its corpus size, and choosing one in the same
change that moves it is what ADR-0048 refused.

## Consequences

- `relation_path_recall` reaches **1.0000** and **ADR-0034's cause list is fully
  discharged.** Its register row's trigger — "that design decision is settled" —
  is satisfied, and choosing the threshold is now the open question.
- `SymbolStore.get_many` is added so labelling a handful of relation endpoints
  reads a handful of rows. `list_for_snapshot` is O(repository) and text search
  is the most common intent; using it here would have put a full symbol load on
  every query, which Section 10.3 asks callers to avoid.
- `LexicalSearchService` takes `relations` as a **required** argument. Defaulting
  it to `None` would have made a missing store indistinguishable from a genuinely
  empty result.
- `/v1/search/text` gains the field too, because the adapters share the service.
  That is the intended consequence of Section 4.5, not a side effect.
- `baseline-phase-3` and `baseline-phase-4` each move by exactly two lines.

## Security and Privacy

None. The edges were already stored, validated and snapshot-scoped; this reports
them through a field the contract already defines. No new data movement, no
provider call, no logging change.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`, `SCHEMA_VERSION` stays `14`. No `PARSER_BUNDLE_VERSION`,
`RESOLVER_VERSION` or `CHUNKER_VERSION` move, so **no re-index is required**.
Rollback is reverting the commit and regenerating the two baselines.

## Approval

Ruled by the user on 2026-08-17, choosing resolved-edges-only over both
alternatives, and deferring the gate target until the resulting number was
known.
