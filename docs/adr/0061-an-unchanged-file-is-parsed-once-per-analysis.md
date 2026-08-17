# ADR-0061: An unchanged file is parsed once per analysis, not once per side

- Status: accepted
- Date: 2026-08-18
- Decision owners: user/product (asked for the parsing cost to be fixed) and
  implementing agent
- Supersedes: none — it **corrects a measurement claim in ADR-0060**
- Related: ADR-0060 (the preflight measurement), ADR-0005 (two states, one
  engine), ADR-0043 (line endings are not a change)

## Context

ADR-0060 measured a commit-range preflight over this repository at **635 s**
and attributed 99.5% of it to `parse_base` + `parse_target`. The register's
remedy row said: do not re-parse unchanged files.

The two sides share every file the change did not touch. And every field of the
`ParseRequest` the engine builds comes from `(relative_path, language,
content)` — `repository_id` and `snapshot_id` are the **same constant** on both
sides, and `file_id` is derived from the path. So for an unchanged file the two
sides construct a **byte-identical** request, parse it twice, and discard one of
two identical answers.

## Decision

**Cache parses for the duration of one `analyze()` call**, keyed on
`(relative_path, language, content digest)`.

**Scoped to the call deliberately.** Same process, same parser instance, same
bytes: reuse is correct by construction and there is no invalidation question
to get wrong. A cache that outlived the call would have one — which is exactly
why the register's remedy row asked for a ruling, and why this change does not
need it.

The key uses a digest of **the bytes handed to the parser**, not the state's
declared `content_hash`. ADR-0043 normalises line endings on the way in, so the
state's own accounting can differ from what was actually parsed; keying on the
real input cannot drift.

## Measured — and the headline number is a count, not a clock

**Parses during one working-tree preflight over a 303-file repository: 305.**
Without reuse it is ~606; with perfect reuse ~304. The +1 is the one genuinely
changed file, correctly parsed on both sides.

That is a **deterministic** result and the reason this record leads with it.
The machine changed materially during this session — `cold index`, a path this
change does not touch, moved **343 s → 549 s** between two runs — so wall-clock
comparisons across runs were worthless. Counting is immune to that.

| Evidence | Result |
| --- | --- |
| parser calls per preflight | **606 → 305** |
| `baseline-phase-0/-3/-4` `--check` | exit 0, empty `git diff` |
| suite | 2268 passed |

## The correction to ADR-0060

**ADR-0060 said "99.5% is parsing". It is 99.5% *parse plus resolve*, and the
split was never measured.** The `parse_base` and `parse_target` timers wrap
`_analyze_state`, which parses **and then calls `self._resolver.resolve(...)`
over the whole state**. Resolution runs per side regardless of any parse cache.

Measured on a 300-module repository: of **477 ms** under those two timers,
roughly **127 ms is resolution** and **350 ms is parsing** — resolution is about
**27%**. Extrapolating that split to the real repository would be guesswork and
is not done here.

> **This paragraph first said "766 ms of 2137 ms", and both numbers were
> wrong.** They were taken on a machine under heavy load — the same instability
> that made wall-clock comparison useless everywhere else in this record — and
> the 766 ms counted **three** `resolve()` calls when only **two** are inside
> these timers. A preflight resolves three times: the indexing refresh, then
> base, then target, and the refresh is not part of `parse_base`/`parse_target`.
> Corrected on re-measurement (ADR-0062). The mistake is left visible because
> the first version of it was used to explain a failed prediction, and an
> explanation resting on a wrong number is worth flagging rather than quietly
> replacing.

This is why the fix does not halve the wall clock even though it halves the
parse count, and why the prediction stated before the measurement — "roughly
halves, 632 s → ~316 s" — **was wrong**. It was wrong for a reason worth
keeping: a timer named `parse_*` was assumed to time parsing.

**`parse_target` is no longer comparable to `parse_base`.** Whichever side runs
first now absorbs the shared files, so that split reports *order*, not effort.
Their sum is the only meaningful figure, and the call site says so.

## What is not claimed

- **No end-to-end second-count on a real repository.** The wall-clock effect of
  this change is unverified, because the machine was not stable enough during
  this session to measure it. The mechanism is confirmed; the payoff is not
  quantified. Anyone quoting a speedup from this record is quoting something it
  does not contain.
- **Preflight is still O(repository).** Every file is still parsed once per
  analysis and resolved once per side. This removes a *duplicate* pass, not the
  pass itself.
- **Resolution is untouched** and is now the larger share of those timers on at
  least one profile.
- The remaining step — reusing symbols from the stored index so unchanged files
  are not parsed *at all* — still needs the ruling the register asks for, and is
  deliberately not attempted here.

## How it is guarded

Three call-counting tests in `tests/integration/test_engine_parse_reuse.py`,
written before the change and failing on it: **6 parses for 4 distinct inputs**.

One guards the opposite direction, and it is the one that matters most: a file
whose content genuinely differs **must** still be parsed on both sides. Keying
reuse on the path alone would hand the base parse back for the target and report
a changed file as unchanged — a silent wrong answer rather than a slow one.

A third asserts the report itself is unchanged through the real registry.

## Alternatives

**Persist the cache across analyses.** Rejected for now: it is where the real
remaining win is, and it is also where the invalidation question lives — parser
version, normalisation version, and content identity all become inputs. It
deserves its own record rather than being smuggled in behind a correct-by-
construction change.

**Reuse the stored snapshot's symbols for the target side.** The register's
original remedy. Not attempted here: it needs a ruling on when stored symbols
may be trusted, and `SnapshotStateView` — the obvious vehicle — does not
actually avoid parsing (ADR-0060).

## Security and Privacy

None. An in-memory dictionary scoped to one call; no I/O, no persistence, no
data movement, no logging change.

## Migration and Rollback

No schema, contract, or version constant changes. `contract_version` stays
`1.1`, `SCHEMA_VERSION` stays `14`. Output is byte-identical, so **no re-index
is required**. Rollback is reverting the commit.

## Approval

The user asked for the parsing cost to be fixed on 2026-08-18, and for the
change to be committed only once the measurement confirmed it. The confirming
measurement is the parse count — 606 → 305 — together with byte-identical
baselines; the wall-clock prediction is recorded above as **not** confirmed.
