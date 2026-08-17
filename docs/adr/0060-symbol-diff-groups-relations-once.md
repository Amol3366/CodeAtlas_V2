# ADR-0060: Symbol diff groups relations once, not once per symbol

- Status: accepted
- Date: 2026-08-18
- Decision owners: user/product (asked for the fix) and implementing agent
- Supersedes: none
- Related: ADR-0005 (change-assurance engine design), ADR-0042 (a symbol pairs
  within its file), ADR-0041 (nested config keys hash their own value),
  ADR-0003 (the corpus is never edited to move a number)

## Context

The Deferred Register carried "Preflight takes >15 minutes on a 664-file
repository" as **an observation, not yet a measured defect** — noticed twice
during ADR-0044 verification and written down neither time until it was
recorded on 2026-08-13. Measuring it produced one confirmation, one defect, and
three corrections to the record — **and then showed that the defect is not what
makes preflight slow.** That last part is in "This is not the fix that matters"
below, and it is the finding to read first.

**The documented cost is real.** Holding the change at exactly one edited
function body and sweeping the repository across 100/200/400/800 generated
modules, preflight scales with the repository: 8× the files gives 7.12× the
time, a log-log exponent of **0.95**. Cost tracks repository size, not change
size, exactly as `docs/operations/change-analysis.md` says.

**One stage did not scale like the others.**

| Stage | Fitted exponent |
| --- | ---: |
| `symbol_diff` | **2.02** |
| `parse_base` / `parse_target` | 1.08 / 1.07 |
| `file_diff` | 0.93 |
| `findings` / `impact` | 0.86 / 0.83 |

An exponent of 2.02 is not a slow stage; it is a quadratic one, and it was
invisible because at small repositories it is a rounding error — 2.8% of engine
time at 100 modules, 18.8% at 800, growing 4× per doubling while everything
else grows 2×.

## The defect

`_dependency_changed` and `_binding_span` each need **one symbol's outgoing
edges**, and both found them by filtering the whole relation list:

```python
base_edges = {
    edge_key(relation, context.base_bindings)
    for relation in base_relations
    if relation.source_symbol_id == base_symbol.symbol_id
    and considered(relation, context.base_names)
}
```

Both are called once per surviving symbol pair. Symbols and relations both grow
linearly with the repository, so the product is **O(symbols × relations)**.

**The worst case is an unchanged repository, not a large diff.** The dependency
check runs precisely when a symbol's content hash is *unchanged* — that is the
branch asking "did this symbol's references resolve differently even though its
text did not?" So the quadratic is paid on every preflight, in full, and a
bigger diff makes it *cheaper* rather than more expensive.

## Decision

**Group relations by `source_symbol_id` once per analysis, in
`_DependencyContext`, and look them up by key.**

This is the move `_group_by_key` already makes for symbols a few lines earlier,
so it follows the module's existing grain rather than introducing a mechanism.
`_dependency_changed` and `_binding_span` lose their relation-list parameters
entirely — the context already carries every other derived map they need.

Grouping preserves each symbol's relation order. `_binding_span` takes a `min`
and `max` over the lines it collects, so a reordering could not change its
result — but relying on that would be an accident rather than a decision.

## Measured

Same sweep, same machine, before and after:

| modules | `symbol_diff` before | after | speedup |
| ---: | ---: | ---: | ---: |
| 100 | 11.9 ms | 3.9 ms | 3.1× |
| 200 | 43.9 ms | 6.0 ms | 7.3× |
| 400 | 190.0 ms | 10.6 ms | 17.9× |
| 800 | 768.8 ms | **19.7 ms** | **39.0×** |

**Fitted exponent 2.02 → 0.78.** The speedup growing with size is the
signature of removing a quadratic term rather than shaving a constant. The
stage's share of engine time falls from **18.8% to 0.6%** at 800 modules.

**Wall-clock deltas are deliberately not claimed.** They ranged −9.0% to +8.8%
across the four sizes, and that is noise at this precision: `cold_index` at 100
modules moved 2.97 s → 1.81 s between the two runs, a 39% swing on a code path
this change does not touch. The stage timing is a direct measurement of the
changed code and is the number worth quoting.

## Behaviour is unchanged, and that is the point

A pure optimisation has to prove it changed cost and nothing else.
`baseline-phase-0`, `-3` and `-4` all reproduce **byte-for-byte** with `--check`
exit 0 and an empty `git diff`. The full suite passes at 2265 tests.

## How it is guarded

**A scan-counting test, not a timing test.** Timing tests flake on a loaded
machine and would have to be excluded from the gate; counting how many times
the relation sequence is traversed is deterministic. `tests/unit/
test_symbol_diff_complexity.py` passes a `Sequence` that records each
traversal.

Before the fix it reported **51 traversals for 50 symbols and 401 for 400** —
exactly *n + 1*, the quadratic stated as a number. A second test asserts the
count is **identical** across an 8× size jump, so raising the ceiling constant
cannot quietly defeat the guard: only a change in *growth* can.

**Mutation-checked.** Making `_group_by_source` return `{}` fails five tests,
including corpus-level ones in `test_change_adapter.py`, so the grouping is
load-bearing rather than scaffolding that happens to pass. Reverted from a file
copy, never `git checkout --` (ADR-0022, ADR-0042).

## Three corrections to the record, made in the same change

**1. The "snapshot-reuse path" was attributed to the wrong decision, and is not
unimplemented.** `change-analysis.md` said "the snapshot-reuse path decision 2
describes is not implemented". Decision 2 is the Git front-end **security
posture**; the design is decision **1**. And `SnapshotStateView` is not missing
— it exists at `analysis/states.py:315` with four integration tests and **zero
production callers**, the same shape as the `prune` that existed from Phase 2
until P6-08 found nothing called it.

**2. Wiring it in would not have fixed this.** Its `read_file` still reads every
file's bytes from disk and hashes them; only the directory *scan* is avoided,
not the read or the parse. The note as written would have sent the next reader
at a remedy that does not address the cost.

**3. The oversized-file paragraph was stale.** It described a tracked file over
2 MB as failing the analysis outright and the item as "open". ADR-0045 closed
that on 2026-08-15 and skip-and-declare has been live since.

## This is not the fix that matters, and the real repository says so

The synthetic sweep was then checked against **CodeAtlas itself** — 715 tracked
files, 11,419 symbols — using a commit range, so both sides are
`GitBlobStateView` and nothing reads the live tree.

**The register's ">15 minutes" is reproduced: 635.59 s, 10.6 minutes**, stable
across three runs (635.62 / 635.59 / 632.21). It is a real defect, not an
anecdote.

| Stage | Real repository | Share |
| --- | ---: | ---: |
| `parse_base` | 316,210 ms | 49.8% |
| `parse_target` | 316,040 ms | 49.7% |
| `file_diff` | 2,414 ms | 0.4% |
| `symbol_diff` (after this fix) | **246 ms** | **0.04%** |
| `findings` / `impact` | 113 / 50 ms | ~0.03% |

**Parsing is 99.5% of the cost.** Extrapolating the old quadratic to 11,419
symbols puts `symbol_diff` at roughly 17 s — so **this change removes about
2.7% of the real-world time.** The quadratic was real, the fix is correct, and
it is not the remedy for the reported problem. Recording that is the point:
a 39× speedup on a stage worth 2.7% is a true number that would mislead anyone
who read it alone.

**The synthetic profile mis-weights the stages, and an earlier draft of this
record repeated the error.** It said "`file_diff` is the largest single stage,
ahead of both parses" — true at 800 generated modules (1339 ms of 3367 ms),
**false on the real repository**, where `file_diff` is 0.4% and parsing is
99.5%. The generated modules are ~15 lines each; this repository's files are
far larger and include 2,430 document sections, one Markdown file of 12,756
lines among them. **A synthetic profile measures scaling honestly and
proportions dishonestly** — the exponents it produced hold, the shares it
produced did not.

**So `docs/operations/change-analysis.md` was right all along**: "the engine
parses both full states on every analysis; the cost is O(repository), not
O(change)". That sentence names the whole problem, and the measurement's main
contribution is confirming it with a number rather than correcting it.

## What this does not fix

- **The O(repository) parse remains, and it is 99.5% of the cost.** The real
  remedy is not to parse unchanged files twice on every analysis. Note that the
  unused `SnapshotStateView` does **not** provide this: it still reads and
  hashes every file. A parse cache keyed by content hash would, and that is a
  design question with its own correctness and invalidation concerns — not a
  fix to fold into this record.
- **44–58% of preflight wall time is outside the engine** on the synthetic
  profile. On the real repository the engine stages account for essentially all
  of it, which is another proportion the synthetic profile got wrong.
- **Cold indexing this repository takes 343 s.** Measured incidentally, a
  different code path, and absent from the register — recorded as its own row
  rather than folded in here.

## Alternatives

**Leave it; it is only 19% of engine time.** Rejected: 19% is what a quadratic
looks like just before it stops being ignorable, and the fix is a dozen lines
following an existing pattern.

**Cache per-symbol lookups lazily.** Rejected as strictly worse — same result,
more state, and a cache invalidation question where a plain grouping has none.

## Security and Privacy

None. An indexing-order change inside one pure function; no I/O, no data
movement, no logging change.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`, `SCHEMA_VERSION` stays `14`. **No `PARSER_BUNDLE_VERSION`,
`RESOLVER_VERSION` or `CHUNKER_VERSION` move, so no re-index is required** —
the output is byte-identical. Rollback is reverting the commit.

## Approval

The user asked for the quadratic to be fixed on 2026-08-18, after the
measurement that found it was reported.
