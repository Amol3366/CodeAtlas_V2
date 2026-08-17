# ADR-0062: Resolution is not cached, and the measurement says why

- Status: accepted
- Date: 2026-08-18
- Decision owners: user/product (asked for resolution to be cached) and
  implementing agent
- Supersedes: none — it **corrects a measurement claim in ADR-0061**
- Related: ADR-0061 (parse reuse within one analysis), ADR-0060 (the preflight
  measurement), ADR-0005 (two states, one engine)

## Context

ADR-0061 removed the duplicate parse and, in explaining why wall time did not
halve, said the `parse_base` / `parse_target` timers also wrap resolution. The
register gained a row for it, and the next instruction was to cache resolution
too.

Three things had to be true for that to be worth doing: resolution has to be a
meaningful share of the cost, it has to be cacheable in the shape parsing was,
and there must not be a cheaper defect underneath. **None of the three holds.**

## Measured

**1. Resolution is linear.** Swept over 100/200/400/800 generated modules,
resolving in isolation:

| modules | files | symbols | references | resolve |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 103 | 300 | 1,294 | 19.1 ms |
| 200 | 203 | 600 | 2,594 | 39.4 ms |
| 400 | 403 | 1,200 | 5,194 | 86.6 ms |
| 800 | 803 | 2,400 | 10,394 | 204.4 ms |

**Fitted exponent 1.14.** There is no `symbol_diff`-shaped defect hiding here:
the cost is proportional to the references it resolves, which is what
resolution is.

**2. It is a modest share, and smaller than ADR-0061 said.** On a 300-module
working-tree preflight: `parse_base` + `parse_target` = 477 ms, of which
**~127 ms is resolution** (two calls at ~63 ms) and ~350 ms is parsing. Against
a 2128 ms wall clock, resolution is roughly **6% of preflight**.

**3. A preflight resolves three times, not twice.** The indexing refresh inside
`analyze_working_tree` resolves before the engine runs at all, and that call is
**outside** both parse timers.

## Decision

**Do not cache resolution.** Record the measurement and the reason.

**It is not cacheable in the shape parsing was.** Parsing is per file, and the
two sides share every file the change did not touch — that is what made a
content-keyed cache hit almost every time. Resolution takes the **whole state**:
`resolve(files, symbols, references)`. The two sides differ by exactly the thing
being analysed, so a whole-state key **cannot hit within a call**. The only case
where it would is a change that changes nothing, which is the case nobody runs
preflight for.

**Making it incremental would contradict a stated design property, not just add
risk.** `_analyze_state`'s own comment says resolution runs over the whole state
"rather than the changed files alone. An edge is only meaningful against a
complete symbol table". That is load-bearing: adding a symbol can make a
reference in an **unchanged** file resolve where it previously did not, and
deleting one can break a reference nowhere near the diff. An incremental
resolver would have to compute exactly that blast radius — the problem the whole
engine exists to answer — before it could answer it.

**And it is 6% of the cost.** Spending that risk to chase 6%, while the parse
pass it sits beside is untouched and O(repository), inverts the priority.

## The correction to ADR-0061

ADR-0061 said "of 2137 ms under those two timers, 766 ms is resolution". **Both
figures were wrong.**

- They were measured while the machine was under the load that made every
  wall-clock number in that session unusable — the same instability the record
  itself warns about two paragraphs earlier, and then relies on.
- The 766 ms summed **three** `resolve()` calls when only two are inside those
  timers.

Re-measured on an unloaded machine: **477 ms under the timers, ~127 ms of it
resolution.** ADR-0061 is corrected in place, with the original left visible.

**The lesson is narrower than "be careful with timings".** ADR-0061 used a
number to explain why a prediction failed. An explanation is exactly where a
wrong number does the most damage, because it *satisfies* — the story closes and
nobody re-measures. The parse-count claim in that record was checked by counting
and stands; the resolution claim was not, and did not.

## What would actually pay

Unchanged from ADR-0061's closing: **do not parse unchanged files at all.**
Parsing is ~350 ms of 477 ms on this profile and dominated the real-repository
measurement. That needs symbols from the stored index and a ruling on when they
may be trusted, which is still its own register row.

## Alternatives

**Cache resolution across analyses.** Rejected: the inputs differ per analysis
by construction, so the hit rate is near zero for the same reason it is within a
call.

**Cache `_build_index` alone**, the part of resolution that indexes symbols by
name. Not measured separately and not pursued — it is a fraction of a stage
worth 6%, and the same whole-state key problem applies.

## Consequences

- **No code change.** This record is a measurement and a decision not to act.
- The register's "resolution runs per side and is not cached" row closes as
  *measured and declined*, rather than staying open as if it were pending work.
- ADR-0061's resolution figures are corrected; its parse-count result is
  unaffected.

## Security and Privacy

None. No code changed.

## Migration and Rollback

Not applicable. `contract_version` stays `1.1`, `SCHEMA_VERSION` stays `14`.

## Approval

The user asked for resolution to be cached on 2026-08-18. This record declines
on measurement and states the three reasons, so the decision can be overridden
on evidence rather than re-derived.
