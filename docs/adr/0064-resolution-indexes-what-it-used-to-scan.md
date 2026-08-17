# ADR-0064: Resolution indexes what it used to scan

- Status: accepted
- Date: 2026-08-18
- Decision owners: user/product (asked for the bottleneck to be fixed) and
  implementing agent
- Supersedes: none
- **Corrects: ADR-0060, ADR-0061 and ADR-0062**, all three of which attribute
  preflight cost to the wrong stage
- Related: ADR-0063 (index reuse declined), ADR-0003 (the corpus is not edited
  to move a number)

## The measurement everything else was built on was wrong

Preflight on this repository takes 635 s. ADR-0060 said **99.5% of it is
parsing**. ADR-0061 corrected that to *parse plus resolve* and left the split
unmeasured. ADR-0062 measured resolution at ~**6% of preflight** and declared it
**linear**.

All three are wrong, and they are wrong because a timer named `parse_base` was
read as timing parsing. It wraps `_analyze_state`, which lists, reads, parses
**and resolves**. Timing the four separately on the same `GitBlobStateView` the
635 s came from:

| stage | seconds | share |
| --- | ---: | ---: |
| `list_files` | 1.25 | 0.4% |
| `read_file` (+ hash) | 0.07 | 0.0% |
| `parse` | 8.14 | **2.5%** |
| `resolve` | **310.24** | **97.0%** |
| total, one side | 319.69 | |

**Parsing the entire repository takes 8 seconds.** The stage three records spent
their remedies on is 2.5% of the cost. Resolution — the stage ADR-0062 measured,
declined to cache, and called a modest linear share — is essentially all of it.

## Why the earlier resolution measurement said 6% and linear

This is the part worth keeping, because the number was not carelessly taken. It
was taken on `measure_phase4_perf.py`'s **generated** corpus, which emits
~15-line Python modules and nothing else.

The quadratic term lives in document references. On the real repository:

| reference class | count | share | comparisons it performed |
| --- | ---: | ---: | ---: |
| `<mention>` | 112,265 | 69.9% | **1,291,272,030** |
| ordinary | 43,157 | 26.9% | — (indexed already) |
| `<route>` | 5,265 | 3.3% | 60,558,030, each with a regex tokenize |

`DOCUMENTS` is 117,471 of 160,687 references. The generated corpus contains **no
Markdown, no document sections, and therefore no mentions and no routes** — so
the sweep that fitted exponent **1.14** was fitting a curve on the one reference
class that was never quadratic. The exponent was correct for what it measured
and meaningless for the repository it was used to describe.

Register row 135 already says a synthetic corpus "measures scaling honestly and
proportions dishonestly". It measured *scaling* dishonestly too, whenever the
term that dominates is carried by a file type the generator does not emit.

## What was actually wrong

`resolution.py`'s module docstring has claimed since it was written:

> The work is a pass over an in-memory name index built once per snapshot, so it
> is O(references), not O(references x symbols).

Three call sites contradicted it, each iterating `symbols_by_id.values()` from
inside a per-reference loop:

| site | scanned per | filter it was applying |
| --- | --- | --- |
| `_resolve_mention` | every mention | `kind not in _UNMENTIONABLE_KINDS`, `name.lower() == word` |
| `_RouteIndex.handlers` | every route | `kind in _HANDLER_KINDS`, `tokens_match(..., name_tokens(name))` |
| `_derive_config_edges` | every document section | `kind is CONFIG_KEY` |

Every one of those predicates depends only on the **symbol**, so all of them
belong in the index the docstring already promised. The profile shows what that
cost: `str.lower` called **880,172,549** times, and `name_tokens` — a regex
split — called **10,529,048** times, once per symbol per route.

Three smaller recomputations went with them: `_resolve_module` walked the whole
module table per unqualified specifier, `_candidate_levels` recomputed a file's
directory string per sibling candidate, and `_dotted_paths` — a pure function of
its symbol — was called **2,226,354** times, once per (section x config key).

## Decision

Move every symbol-only predicate into `_Index`, built once per snapshot:

- `mentionable_by_lower_name` — mentionable symbols bucketed by lowercased name
- `handlers_by_token` — handler symbols bucketed by each word of their name
- `config_key_paths` — config-key symbols with their dotted paths pre-split
- `module_suffix_to_file` — every dotted tail of every module path
- `directory_of_file` — each file's directory, computed once

and memoize `_RouteIndex.handlers` per route literal, since both of its inputs
(the route's tokens, and the symbols that state it) depend only on the route
while a repository has far fewer distinct routes than route references.

The route index needed one new idea rather than just a bucket. `tokens_match` is
a predicate, not an equality, so it cannot be a dictionary key directly — but
its plural rule is small and closed, so the set of words matching a given word
can be **enumerated** instead of searched for. `routes.matching_forms` returns
that set (`order`, `orders`, `orderes`, and the stem when the word is itself a
plural), which turns "does this route share a word with this identifier" from a
comparison against every identifier into a handful of dictionary hits.

**Measured on this repository, both implementations over the same 706 files in
one process: 313.97 s → 3.55 s, an 88x reduction.** Resolution goes from 97% of
a preflight side to roughly a quarter of a much smaller total.

## Equivalence, because speed is worthless if the edges changed

The projections replace predicates, so the risk is not that a bucket is slower —
it is that a bucket key spells the predicate slightly differently. Three details
had to be preserved deliberately:

- The projections are built from **`symbols_by_id.values()`**, not from the
  input sequence, because a symbol ID appearing twice was collapsed by the dict
  before the inline scans saw it. Building from `symbols` would have counted it
  twice and turned a `RESOLVED` mention into an `AMBIGUOUS` one.
- `_RouteIndex.handlers` **sorts before caching**, so excluding the caller's own
  file afterwards is a filter over an already-ordered list and cannot reorder.
- `module_suffix_to_file` is filled with `setdefault` **in module-table order**,
  which reproduces "the first module path ending with this specifier wins" —
  the linear scan's first-match semantics, and the reason two runs over one
  repository agree.

Verified by running both implementations over this repository's own 706 files in
one process and comparing all 168,605 relations field by field: **identical**,
with identical `ResolutionStats` (41,524 resolved / 1,999 external / 102,869
unresolved / 22,213 ambiguous).

This check is the evidence, not the passing test suite. The suite passes on the
pre-change resolver too — as it should, since behaviour did not change — so it
cannot distinguish a correct index from one whose bucket key is subtly narrower
than the predicate it replaced. Only a real repository has the duplicate symbol
IDs, name collisions and repeated route literals that would expose that.

`RESOLVER_VERSION` is deliberately **not** bumped. It marks changes in what
resolution concludes, and this record changes only how long it takes to conclude
it; bumping it would invalidate stored resolutions for no reason.

## The guard

`tests/unit/test_resolution_complexity.py` counts traversals of the symbol
table, not elapsed time. That distinction is load-bearing here specifically:
wall-clock is what sent three records to the wrong conclusion, on a machine that
moved an untouched path from 343 s to 549 s mid-session.

Two assertions rather than one, following `test_symbol_diff_complexity.py`: a
ceiling, and a direct growth comparison that survives someone raising the
ceiling. Growth is asserted on **both** axes of the product, so a fix that
indexed only one direction cannot pass.

Checked against the pre-change resolver: the two growth guards **fail** on it
(scan count 53 → 403 when references grow 8x), and the three behaviour tests
**pass** on it, which is the correct outcome for tests asserting that behaviour
did not change.

`matching_forms` carries a second guard of its own, because it is the one change
here that could be silently wrong in either direction: one form too few drops
route edges, one too many invents them, and neither surfaces as an error.
`test_route_literals.py` asserts the enumeration and `tokens_match` agree on
every pair of a vocabulary chosen to cover each shape the plural rule can take —
stems, `-s` and `-es` plurals, words that merely end in those letters, and the
single characters where stripping a suffix leaves nothing.

`tokens_match` therefore stays, with no production caller. That is deliberate
and is stated in its docstring: it is the readable statement of the rule, and
the property test is what stops the index and the rule from drifting apart.

## What this does not fix

**Preflight is still O(repository).** 12.59 s per side is a much better constant
on the same shape, not a different shape. The register's parse-reuse rows stay
closed on their own arithmetic (ADR-0063) — but their premise, that parsing was
worth attacking, is now known to have been false when they were written.

**The persisted parse cache row should close as not worth building.** It targets
the 8 s stage. Its best case was ~1.3% of preflight, and content-keying misses
the most expensive file every run — `docs/plans/PLAN.md` is 26.4% of parse cost
and was touched by all 50 of the last 50 commits.

**Resolution is now worth re-measuring rather than re-reasoned about.** 12.59 s
across 160,560 references is not obviously optimal, and the remaining shape is
unprofiled. That is a register row, not a claim made here.

## Alternatives

**Cache resolution across runs.** Still rejected, and ADR-0062's *reason* for
rejecting it survives its wrong numbers intact: `resolve()` takes the whole
state, so the two sides differ by exactly the thing being analysed, and adding a
symbol can make a reference in an unchanged file resolve. Making the existing
pass 24.6x cheaper does not need that ruling.

**Cap mentions harder.** `MAX_MENTIONS_PER_SECTION` is already 60. Lowering it
would have cut the cost by dropping edges — buying speed with recall, silently.
Rejected: the product's claim is that an edge is never invented and never
quietly dropped.

## Consequences

- Resolution's advertised complexity is now true. The docstring says so, and
  says that keeping it true is a constraint on future lookups.
- Three records carry a correction. ADR-0060's headline, ADR-0061's inherited
  framing, and ADR-0062's 6%-and-linear finding are all superseded on the facts
  while their *design* conclusions stand.
- The general lesson, since this is the fourth correction on one measurement:
  **a timer is named by its author, not by what it wraps.** Every number in
  ADR-0060 through ADR-0062 traces to reading `parse_base` as parse time. The
  cheap check — time the four operations separately — was available the whole
  time and was not run until the fourth attempt.

## Security and Privacy

None. No new inputs, no new outputs, no I/O change. The indexes hold references
to symbol records already held in memory for the duration of one resolution
pass.

## Migration and Rollback

None. `contract_version` stays `1.1`, `SCHEMA_VERSION` stays `14`,
`RESOLVER_VERSION` stays `1.4.0`. No stored data changes shape or meaning, so
rollback is reverting the source file.

## Approval

The user asked for the bottleneck to be fixed on 2026-08-18, after three
consecutive records that measured a proposed remedy and declined it. This one
found the cost in a stage those records had measured and dismissed, and the
correction to them is stated rather than folded in.
