# ADR-0080: The release gate measures the profile it can reproduce

- Status: accepted
- Date: 2026-09-03
- Decision owners: user/product and implementing agent
- Supersedes: none

## Context

`AGENTS.md` §19.3 declares two performance targets — **changed-file refresh
p95 ≤ 2 s** and **warm change-preflight p95 ≤ 10 s** — and
`scripts/measure_phase4_perf.py` implements them, exiting 1 if either misses.

ADR-0064 established that the synthetic profile those targets are measured on
**cannot contain the dominant cost**: its generated modules emit no documents
mentioning the symbols they define, so the work a real repository does is
structurally absent. `--profile realistic` was added to emit that shape.

RW-06 measured both profiles (2026-09-02, 10 runs per point, idle Windows 11
machine, 24 logical CPUs, Python 3.12.12). Full table in
`docs/evaluation/phase4-realistic-profile.md`:

| Modules | Refresh p95 (synthetic → realistic) | Preflight p95 (synthetic → realistic) |
| ---: | --- | --- |
| 40 | 0.406 → 1.376 ✅ | 0.860 → 2.051 ✅ |
| 80 | 0.590 → **2.111 ❌** | 1.205 → 3.794 ✅ |
| 160 | 0.975 → 4.329 ❌ | 2.001 → 7.268 ✅ |
| 300 | 1.799 → 9.427 ❌ | 3.750 → **13.844 ❌** |

Two findings the register did not carry. Refresh first misses at **80
modules**, confirming the register's claim; and at 300 modules the realistic
profile **also misses preflight** — the register described this as a refresh
problem and it is both. The realistic/synthetic ratio widens with size (3.4× at
40 modules, 5.2× at 300), so it is not a constant offset a one-off target
adjustment would absorb.

**Nothing got slower.** No regression is being reported. The realistic profile
was added precisely because the synthetic one was known to be unrepresentative,
and it is doing what it was built to do. The only question is which profile the
release gate measures.

## Decision

**The gate keeps measuring the synthetic profile, and the realistic figures are
recorded beside it as a declared limit.**

Three things follow, and all three are the point rather than side effects:

1. The synthetic tree stays **byte-identical**, because the tracked Phase 4
   baseline was taken on it and changing the generator would silently redefine
   every historical number.
2. `docs/evaluation/phase4-realistic-profile.md` is the permanent record of what
   the gate does *not* cover, and `AGENTS.md` §19.3 now names the profile its
   targets are measured on, so the gate's scope is stated in the contract rather
   than inferable only from a script.
3. The register row becomes an **accepted limit with a trigger**: it reopens
   when a user reports preflight or refresh latency on a real repository, or
   when the realistic tree is made tracked and reproducible.

## Alternatives

- **(b) Re-gate on realistic and track a new baseline.** The technically better
  answer and rejected on timing, not on merit. The realistic tree is not
  currently tracked or reproducible the way the synthetic one is, so a baseline
  must be established first — and **the gate would be red today at 80 modules**.
  Opening a red release gate is a decision to accept a failing gate until the
  cost is fixed, which is the opposite of what a closeout is for. Named here so
  the next person does not have to rediscover that it was considered.

- **(c) Re-gate on realistic and relax the target to what it supports.**
  **Refused, and refused twice.** ADR-0048 already ruled that *"a number chosen
  to be passed says less than it appears to"*, and ADR-0032 and ADR-0033 each
  had to correct a threshold picked that way. A ≤ 10 s target chosen because
  9.427 s is what the profile happens to produce would describe the
  implementation rather than commit to a product behaviour. Adopting (c) would
  require an ADR overturning ADR-0048, not merely this one.

## Consequences

Positive: the gate stays reproducible and green, the tracked baseline keeps its
meaning, and the shortfall is written down in the contract instead of living in
a script nobody reads.

Negative, and stated plainly: **the release gate goes on passing on a profile
ADR-0064 showed cannot contain the dominant cost.** A packaged build can
therefore satisfy §19.3 while being slower than 2 s on a real repository of
modest size. That is a known, accepted gap, not an oversight, and any
performance claim made from the gate must say which profile produced it.

RW-06's figures are **p95 over 10 runs**, adequate to locate a threshold
crossing and *not* adequate to publish. They must not reach the README, which
quotes 20-run figures from `measure_phase7_perf.py` on the packaged artifact.
The JSON outputs are deliberately untracked: they are machine-specific, and a
tracked file here would read as a baseline.

## Security and Privacy

None. Measurement only; no data movement, no trust boundary, no logging change.

## Migration and Rollback

No migration and no code change. `SCHEMA_VERSION` 14, `contract_version` 1.1,
`PARSER_BUNDLE_VERSION` 1.9.0, chunker 1.1.0, resolver 1.5.0 — **no reindex.**
Rollback is adopting (b), which requires the tracked realistic baseline this
decision declines to build now.

## Approval

Approved by the user 2026-09-03. Scope approved: leave the Phase 4 performance
gate on the synthetic profile, record the realistic figures as a declared limit
in `AGENTS.md` §19.3 and the evaluation brief, and convert the register row to an
accepted limit with a named trigger. Option (c) was presented as foreclosed by
ADR-0048 and was not selected.
