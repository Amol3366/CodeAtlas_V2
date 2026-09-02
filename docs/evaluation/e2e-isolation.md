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
