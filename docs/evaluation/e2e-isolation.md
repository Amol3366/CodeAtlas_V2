# The e2e cross-suite failure: RV-01's experiment, and the premise it killed

Measured 2026-09-03 (RV-01). **Verdict: FALSIFIED.** The plan and its design
document both asserted that this failure had stopped being intermittent. A third
full run passed, so that assertion is withdrawn.

## What was claimed

`docs/superpowers/specs/2026-09-03-release-validation-design.md` argued:

> Two runs out of two failed today. A defect that reproduces is diagnosable, and
> should stop being carried as a flake.

That was written after two failures and before a third run existed.

## What the runs actually say

| # | Run | Result |
| --- | --- | --- |
| 1 | full `playwright test`, branch `plan/project-closeout` | **FAILED** — `restart-persistence`, 7x wrong value |
| 2 | full `playwright test`, `main` | **FAILED** — same spec, plus `stream-reconnection.spec.ts:140` |
| 3 | `restart-persistence` alone, `main`, `--project=firefox` | passed (21.9 s) |
| 4 | full `check_phase7.ps1 -SkipSync`, merged `main` | **PASSED** — 8 skipped, 14 passed, gate exit 0 |

**Two failures in three full runs.** That is intermittent — frequent, but
intermittent. The register's original wording ("an intermittent cross-suite
state leak") was right, and RV-01's premise was wrong.

## What this does and does not settle

**Does not settle:** the mechanism. The worker-scoped-seed reading remains a
*hypothesis*. It is consistent with everything observed — `seeded` really is
`{ scope: "worker" }` (`apps/web/e2e/support/fixtures.ts:22-30`), `seed()` really
does `rmSync(workdir)` once (`backend.ts:49-50`), one worker really does run all
22 tests across both projects, and the spec's own authors really did document
the shared database at `restart-persistence.spec.ts:41-45`. But a hypothesis
consistent with the evidence is not a demonstrated mechanism, and run 4 shows
the same code path completing cleanly.

**Does settle:** that the planned fix could not have been verified. RV-02's
verification step was "run the full suite and see it go green". Against an
intermittent failure that passes on its own two runs in three, a green run
proves nothing — it is the outcome you get most of the time anyway. **Any fix
shipped on that evidence would have been indistinguishable from luck.**

## Why the experiment was not completed

RV-01 Step 2 (`--project=firefox` alone) exists to isolate "Chromium ran first"
as the variable. It is only meaningful against a *reproducible* baseline: with
Step 1 passing, a Firefox-only pass distinguishes nothing, because the full run
passes too.

## What would actually settle it

Not more single runs. The failure needs a **repetition count**, which
Playwright supports directly:

```bash
cd apps/web
pnpm exec playwright test --repeat-each=10 > repeat.txt 2>&1
```

Ten full runs give a failure *rate*. A fix is then defensible if the rate goes
to zero across the same number of runs, and not before. That is a ~10-minute
job and it is the honest next step, but it is a decision to spend that time on
a test-harness defect during a closeout, so it is left as a recommendation
rather than taken unilaterally.

## Disposition

The Deferred Register row stays **DEFERRED**, and gains run 4 as a third data
point plus the mechanism hypothesis with its status stated. It is **not**
closed: closing it would require demonstrating the mechanism, and this
experiment did not.

## Rate measured 2026-09-03 — 0 failures in 140, and the hypothesis is retired

`pnpm exec playwright test --repeat-each=10`, exit **0**: **140 passed, 80
skipped**, 10.3 minutes. `restart-persistence` on Firefox ran **10 of 10
green**, at test positions 114, 125, 136, 147, 158, 169, 180, 191, 202, 213.

### Today's totals

| | |
| --- | ---: |
| Firefox executions of this spec | ~16 |
| Failures | **2** |
| Consecutive passes since the second failure | **14** |

Both failures were the session's **first two** full runs.

### This argues AGAINST the mechanism this document proposed

The hypothesis was state accumulation: one worker, one `seed()`, conversations
from earlier specs piling up until `restart-persistence` trips over them.

`--repeat-each=10` is close to a direct test. It reuses **one worker**, so the
seed still fires once and every repetition runs later than the last. **If
accumulation were the cause, position 213 should be far more dangerous than
position 15.** It passed, and so did the nine before it.

The state also did not pile up the way the hypothesis requires. After 140
executions the database held **7 conversations and 6 user messages** — nothing
like ten repetitions' worth of residue. Either the harness resets more often
than one-seed-per-worker implies, or conversations are not retained as assumed.
Both readings weaken the hypothesis.

**It is retired, not confirmed.** The failure is real — two captures exist, one
with the conversation rows — but it is rare, not reproducible on demand, and
its mechanism is unknown.

### What is deliberately not concluded

Both failures cluster in the session's first two runs, which is the same shape
the performance misses had before they turned out to be machine load. **That is
recorded as an observation and not as a claim.** Twice in this session a
pattern was mistaken for a mechanism — the "no longer intermittent"
reclassification and the parser-bump attribution — and both died on a
measurement. A third guess is not offered.

### Consequence for any future fix

A fix here cannot be verified by running the suite. At a rate of roughly 2 in
16 — and 0 in the last 140 — a green run is the overwhelmingly likely outcome
whether or not anything was fixed. **Any candidate fix needs a reproduction
first**, or a mechanism demonstrated from the code, and neither exists today.
That is why the planned RV-02 change was cancelled rather than shipped.
