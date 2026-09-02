# Release validation, and the e2e seeding defect that blocks it — design

Status: proposed
Date: 2026-09-03
Author: Claude Code `claude-opus-5`
Plan: `docs/superpowers/plans/2026-09-03-release-validation.md`

## The problem

The 2026-09-03 closeout (CO-01 to CO-08, merged `0ff2a86`) left five release
validation steps unrun, and recorded that plainly in the merge commit:

```
scripts/check_phase7.ps1 -Package
scripts/check_phase7.ps1 -Semantic -Package
scripts/check_phase7.ps1 -SkipSync -Perf
# and release-validation step 5, by hand
```

**All four gate legs are blocked behind one failure**, and this is the finding
that shapes the whole design.

## Why nothing can pass until the flake is settled

`Invoke-Checked` (`scripts/check_phase7.ps1:45-65`) throws on any non-zero exit:

```powershell
& $Command @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE."
}
```

The Playwright step is an `Invoke-Checked` call, and it sits **above** the
`-Semantic`, `-Package` and `-Perf` blocks. So a Playwright failure aborts the
script before any of those legs run. **`check_phase7.ps1` cannot exit 0 while
`restart-persistence` fails, and `-Package` cannot even be reached.**

This is not a matter of tolerating a known-flaky test in a report. The gate is
structurally red.

## ~~The failure is not intermittent any more~~ — WITHDRAWN 2026-09-03

> **This section was wrong and is kept as written, struck, because the error is
> the reusable part.** It was authored after two failing runs. A third full run
> — the gate itself, `check_phase7.ps1 -SkipSync`, exit **0**, 8 skipped / 14
> passed — passed cleanly. Two failures in three runs is *intermittent*, which
> is what the register said all along.
>
> The error was reclassifying a defect on a sample of two, in a document arguing
> that other people's figures should be re-derived rather than inherited. The
> full account and the disposition are in `docs/evaluation/e2e-isolation.md`.
> **RV-02 does not proceed**: its verification was "run the full suite and see
> it go green", which against a failure that passes two runs in three proves
> nothing a fix would have to earn.

## The original argument, as written

The Deferred Register carries this as *"an intermittent cross-suite state leak,
observed once with its mechanism visible, and NOT reproduced in three
attempts."* That description is now out of date:

| Run | Result |
| --- | --- |
| 2026-08-19, post-merge gate on `main` | failed, 5x wrong value |
| 2026-09-03, full run on `plan/project-closeout` | **failed**, 7x wrong value |
| 2026-09-03, full run on `main` | **failed**, plus `stream-reconnection.spec.ts:140` |
| 2026-09-03, spec alone on `main`, `--project=firefox` | **passed** (21.9 s) |

Two runs out of two failed today. A defect that reproduces is diagnosable, and
should stop being carried as a flake.

**The isolation run is the tell.** The spec passes alone and fails in a full
run. That is the signature of a state dependency, not a timing race, and it is
why an isolation run can never be used to attribute this one.

## The mechanism, from the code

`apps/web/e2e/support/fixtures.ts:22-30` declares the seed as a **worker**
fixture:

```ts
seeded: [
  async ({}, use) => { await use(seed()); },
  { scope: "worker" },
],
```

and `seed()` (`apps/web/e2e/support/backend.ts:49-50`) begins:

```ts
export function seed(): SeedResult {
  rmSync(workdir, { recursive: true, force: true });
```

A worker fixture is constructed **once per worker**. The config runs
`workers: 1, fullyParallel: false`, and one worker executes **all 22 tests
across both projects**. So the database is wiped exactly once, at the start of
the run, and every Chromium test and every Firefox test afterwards shares it.

Chromium runs first. Its `stream-reconnection` tests pass and create
conversations asking `PaymentService.capture`. Firefox's `restart-persistence`
then runs against a database already holding them.

**The spec's own authors knew.** `restart-persistence.spec.ts:41-45` says so:

> The database is worker-scoped, so `/` redirects into whatever conversation an
> earlier spec left behind, and the app performs more than one navigation while
> a new chat opens.

They guarded it at line 30 with `await expect(page.getByTestId("message-user")).toHaveCount(0)`
— "an empty message list is the app's own signal that the new conversation is
the one on screen". **That guard is what is now failing to hold**: by line 37
the page shows a conversation carrying seven `PaymentService.capture` messages.

The captured evidence agrees: five conversations in one database, four asking
`PaymentService.capture`, and restart-persistence's own present as
`New conversation` with **no user message row at all**.

## What is NOT being claimed

- **Not that the product is broken.** Every backend suite passes (2480), and
  conversation persistence is proven at the storage layer and by the Firefox
  run in isolation. The evidence points at the *test's* isolation assumption.
- **Not that this branch caused it.** `main` fails it too, and worse.
- **Not that the mechanism above is proven.** It is a hypothesis derived from
  reading the fixtures and one capture. The plan's first task is an experiment
  that can falsify it, and every later task is conditional on the result.

## Options for the flake

**(a) Fix the test's isolation assumption.** Scope the assertions to the
conversation the test created, rather than a page-global `message-user`
locator. Smallest change that makes the test say what it means; does not touch
the product. **Recommended if the experiment confirms the mechanism.**

**(b) Make the seed per-project rather than per-worker.** Correct in principle
and expensive: seeding re-indexes a fixture repository, and it would run twice.
It also changes a shared harness that eight specs depend on, during a closeout.

**(c) Quarantine the spec.** Skip it on Firefox as it is already skipped on
Chromium. **This would leave the Phase 5 gate condition it exists to prove —
"history survives a backend restart" — covered by nothing in a browser.**
Rejected unless (a) and (b) both fail.

**(d) Accept a red gate and record it.** Contradicts the closeout.

## Scope boundary

This design covers **verification and test isolation only**. No product
behaviour changes, no version constant moves, no migration, no reindex. If any
task appears to need one, stop and raise it — that is a scope change under
`AGENTS.md` §25.
