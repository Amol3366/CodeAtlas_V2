# ADR-0063: Reusing the stored index cannot lower the parse count

- Status: accepted
- Date: 2026-08-18
- Decision owners: user/product (asked for parse reuse from the stored index)
  and implementing agent
- Supersedes: none — it **closes** the remedy row ADR-0060 opened and ADR-0061
  and ADR-0062 both deferred to
- Related: ADR-0061 (parse reuse within one analysis), ADR-0062 (resolution is
  not cached), ADR-0060 (the preflight measurement), ADR-0005 (two states, one
  engine)

## Context

Three records in a row ended by pointing at the same remaining item: *do not
parse unchanged files at all, from the stored index.* It was carried as the
thing that would actually pay, needing only a ruling on when stored symbols may
be trusted.

**The ruling is not the blocker. The arithmetic is.**

## What the index can supply

Better than expected, and worth recording because it is the part everyone
assumes is the obstacle.

**There is no references table.** The schema stores `symbols` and `relations`
but never `SymbolReference` — the pre-resolution "what the file said" that
`resolve()` consumes. The obvious approach, rehydrating a state and re-resolving
it, therefore needs a new table, a migration, and a `SCHEMA_VERSION` bump.

**But it does not need one.** `AnalyzedState.graph` is a `GraphSide`, and every
field of it is already stored:

| `GraphSide` field | Source |
| --- | --- |
| `symbols` | `SymbolStore.list_for_snapshot` |
| `relations` | `RelationStore.list_for_snapshot` (already resolved) |
| `file_paths` | `FileStore.list_for_snapshot` |
| `test_file_ids` | `FileRecord.classification` |

References are only an *input* to resolution, and the index stores resolution's
*output*. So a side could be rehydrated with no migration at all.

## Why it still cannot help

**Only one side is ever in the index, and it is the wrong one.**

`analyze_working_tree` refreshes the index before comparing
(`change_analysis.py:117`), so the active snapshot corresponds to the **working
tree — the target**. The base is a Git commit read through `GitBlobStateView`,
and **no commit is indexed**.

Now apply ADR-0061. Since that change, each unique `(path, content)` is parsed
**exactly once** per analysis: measured **305 parses for 303 files**, against a
theoretical minimum of ~304. An unchanged file is parsed once and that one parse
serves both sides.

Reusing the target from the index removes the target's *use* of that parse. It
does not remove the parse, because **the base side still needs it** and the base
is not in the index.

```
today (after ADR-0061)      N parses: one per unique file, shared by both sides
target rehydrated from index N parses: base still parses every file
saving                       ~2 parses
```

**For commit-range analysis it is worse.** Base and target are both commits, so
*neither* is the active snapshot, and index reuse yields exactly zero even in
principle.

## Decision

**Do not implement it.** Close the row as measured and declined, rather than
leaving it open as if it were pending work behind a ruling.

The trust ruling that three records deferred to — parser version, normalisation
version, content identity — was never reached, because the change it would
authorise saves nothing. Asking for it would have been asking the user to decide
something that does not matter.

## What was avoided, stated because it looked reasonable

Had the arithmetic not been checked first, this would have been a multi-day
change to the core wedge: rehydrating a state from storage, and **re-keying
every identifier into the analysis ID space**. The engine builds `file_id` from
`_ANALYSIS_REPOSITORY_ID`, while stored records carry the real repository's IDs
— and ADR-0042 has `symbol_diff` pair occurrences *within their file*, using
`file_id`. Mixing a synthetic-ID base with a real-ID target would pair nothing:
**every symbol would report as deleted and re-added**, on the one workflow the
product exists for.

It would also have silently dropped `diagnostics` and `unparsed` for the
rehydrated side, since neither is stored — so `PARSE_FAILED_TARGET` would stop
being emitted, turning a declared hole in the analysis into a clean-looking
result.

Both are the kind of defect this change would have introduced *in exchange for
nothing*.

## What would actually lower the parse count

**Index the base side.** The floor is one parse per unique file per analysis
because one side is always read from Git. Going below it means having a
commit's symbols in storage — indexing historical commits, or persisting a
parse cache keyed by content hash across runs so a file parsed for yesterday's
preflight is not parsed again today.

The second is the tractable one, and it is where the trust ruling actually
belongs: a persisted cache genuinely does need parser-version and
normalisation-version keys, because it outlives the process. **That is a
different piece of work from the one this record declines**, and it is left as
a register row rather than folded in.

## Alternatives

**Store references and re-resolve.** Rejected twice over: it needs a migration
the relations table makes unnecessary, and it would not change the parse count
either, for the same reason.

**Reuse the target side anyway, for the resolution saving.** Rejected on
ADR-0062: resolution is ~6% of preflight and linear, and this would buy at most
half of that at the cost of the ID re-keying risk above.

## Consequences

- **No code change.** A measurement and a decision not to act.
- The remedy row from ADR-0060 closes. Three records deferred to it; it is now
  answered rather than inherited again.
- The parse floor is documented, so the next reader does not re-derive it: after
  ADR-0061 the count is already minimal for a two-sided comparison where one
  side comes from Git.

## Security and Privacy

None. No code changed.

## Migration and Rollback

Not applicable. `contract_version` stays `1.1`, `SCHEMA_VERSION` stays `14` —
and the migration this work appeared to require is precisely what was avoided.

## Approval

The user asked for parse reuse from the stored index on 2026-08-18. This record
declines on arithmetic rather than on the trust question, and states what would
lower the count instead, so the decision can be overridden on evidence.
