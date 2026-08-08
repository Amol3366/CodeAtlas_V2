# ADR-0025: A Nested Configuration Key Is a Symbol

- Status: accepted
- Date: 2026-08-09
- Decision owners: user (approved the lexical work and the line-attribution choice), implementing agent (record)
- Supersedes: none
- Extends: ADR-0024 (the honest denominator this is measured against)

## Context

`lexical_resolution` was 0.3750, and four of its five failures were the same
shape: a dotted configuration key resolved to its parent.

| expected | returned |
| --- | --- |
| `service.port` | `service` |
| `features.audit` | `features` |
| `scripts.test` | `scripts` |
| `server.host` | `server` |

The cause was not ranking and not the query. Probing the index showed the
symbols did not exist:

```
CONFIG_KEY: features, name, private, scripts, server, service
```

`_nested_paths` has always computed the dotted paths. `_config_symbols` joined
them into the `container` field — a display string feeding retrieval text — and
emitted a `CONFIG_KEY` symbol for the **top-level key only**. So `service.port`
was searchable *prose* but not an addressable *symbol*: nothing could cite it,
and search returned the parent because the parent was all there was.

This is the third instance this week of the same shape: data already computed,
then not surfaced as the thing a caller needs. `relation_paths` were computed
for every graph query and discarded for all but `trace` (ADR-0020); `EXPORTS`
evidence carried the wrong end of its edge (ADR-0019); nested keys were
flattened into a summary.

## Decision

**1. Emit a `CONFIG_KEY` symbol per nested path**, across the JSON, TOML and
YAML collectors. The parent keeps its own symbol and its summary — the summary
is what makes the parent findable, the new symbol is what makes the leaf
citable.

**2. Each leaf cites its own line**, located by matching the leaf name as a key
inside its parent's block. `service.port` cites `settings.yaml:3`, the line that
sets it, not the three-line `service:` block. A config lookup that cannot point
at the assignment is barely better than returning the parent, and the product's
claim is that evidence is verifiable at a glance.

**3. The line is found by text match, and a failed match is not invented.**
JSON and TOML paths come from a parsed structure carrying no line information,
so this is a heuristic, not a parse position. A leaf whose line cannot be found
keeps its **parent's range** rather than being given a guessed one — the
citation stays true (the leaf really is inside that block) and merely less
precise. A test pins that fallback.

**4. Sibling leaves cannot collapse onto one citation.** Lines already claimed
within a block are skipped, so `service.port` and `admin.port` cite lines 2 and
4 rather than both pointing at the first `port` found. A test pins it: two
citations pointing at one line would mean one of them shows a reader a position
that does not support the claim.

`PARSER_BUNDLE_VERSION` 1.2.1 → 1.3.0. Existing snapshots are stale until
re-indexed; `indexing.py` already refuses a stale parser bundle rather than
mixing extractions.

## Consequences

| Metric | Before | After |
| --- | ---: | ---: |
| `lexical_resolution` | 0.3750 | **0.6250** (5/8) |
| `symbol_recall_at_10` | 0.7714 | 0.8857 |
| `mean_reciprocal_rank` | 0.8571 | 0.9429 |
| `ndcg_at_10` | 0.7908 | 0.8840 |
| `exact_evidence_rate` / `valid_evidence_rate` | 0.6316 | **0.5647** |
| `containing_evidence_rate` | 0.6974 | **0.6588** |

**The evidence rates fell, and that is the honest cost.** More symbols means
more evidence items, and the new spans do not match the corpus's gold ranges
exactly — the same trade ADR-0018 recorded. Recall and span precision must be
quoted together; either alone misrepresents this change.

### It did not reach the predicted 0.8750, and the reason is a second defect

q021 (`features.audit`) and q022 (`scripts.test`) still fail. The symbols now
exist — this was verified directly against the index — and the failure is
**ranking**:

```
search 'features.audit' -> ['features', 'features.audit', ...]   parent first
search 'service.port'   -> ['service.port', 'service', ...]      leaf first
```

An exact qualified-name match loses to its own parent when the parent's block is
short enough to score higher on term density. A user asking for a specific key
is handed the key's parent.

That is a retrieval defect, not a parsing one, and it is deliberately **not**
fixed here so the two causes stay attributable. It also touches a documented
invariant: `search_text`'s docstring records that the relaxed-fallback design
was chosen so "a query that finds results today finds exactly the same results
after this change". Promoting exact matches breaks that on purpose, which
deserves its own record rather than being folded into a parser change.

The 0.8750 predicted when this work was scoped assumed one cause where there
were two.

### Two things to watch

**Index volume.** Every nested key is now also a chunk, which is what makes
leaves findable, but `MAX_NESTED_KEY_PATHS` is 40 per top-level key. A large
configuration file therefore adds real volume. This has not been measured on
anything larger than the fixtures.

**Two chunking tests were updated**, not weakened.
`test_json_top_level_keys_become_chunks` and
`test_yaml_top_level_keys_are_scanned_by_line` asserted the exact chunk set was
top-level keys *and nothing else*, which this record deliberately makes false.
They keep strict equality with the nested entries added, and now also assert
each leaf's line — a contract change forcing a test update, not a test relaxed
to pass.
