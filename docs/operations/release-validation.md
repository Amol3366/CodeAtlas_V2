# Windows release validation

What to run before calling a build releasable, and — just as important — what
each step actually proves. A checklist whose items are not understood is a
ritual, and rituals pass while products break.

Everything here targets the **packaged artifact**. Phases 0–6 measured a source
checkout, which is the right thing to measure while building and the wrong thing
to ship.

## The sequence

```powershell
# 1. Deterministic gate, including the browser suites, packaged build, and
#    packaged smoke/security tests.
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -Package

# 2. Semantic-local gate and semantic package build. This produces the measured
#    onedir artifact and skips the slow zip step.
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -Semantic -Package

# 3. The Section 19.3 performance targets with embeddings enabled.
#    NOT `-SkipWeb`: that flag exits the script early (it means "backend only,
#    then stop"), so combining it with -Perf returns 0 having measured nothing.
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync -Perf

# 4. The earlier gates. Phases 1 and 2 are EXCLUDED on purpose -- both scripts
#    are marked SUPERSEDED on line 1, and their baselines are frozen history
#    that ADR-0017 deliberately did not regenerate, so they always report
#    "baseline artifacts are stale" and exit non-zero. Running them is not a
#    check, it is a false alarm.
foreach ($n in 0, 3, 4, 5, 6) {
    powershell -ExecutionPolicy Bypass -File "scripts/check_phase$n.ps1" -SkipSync
}

# 5. Install, upgrade, and uninstall, by hand, once.
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
codeatlas doctor
codeatlas serve --web --open
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Uninstall
```

The exact source command `uv run codeatlas serve --web --open` was also probed
on 2026-08-04 after the Settings polish. The running server returned 200 from
`/v1/repositories`, served `/` and `/settings` with
`Cache-Control: no-store, max-age=0, must-revalidate`, loaded a bundle that
contained the new Settings UI, and a browser probe confirmed the Settings
sidebar link performs document navigation. One user browser session still showed
the older Settings view until manual reload, so that observation remains
recorded separately from the release check.

## What each step proves

| Step | Proves | Would otherwise hide |
| --- | --- | --- |
| `-Package` | The binary starts, migrates a fresh database from *bundled* migrations, indexes and resolves a symbol with evidence, serves the SPA and `/v1` on one origin, and upgrades a database written by a real earlier build | A missing data file — migrations and web assets are not modules, so PyInstaller does not find them by analysis. Both fail late: the migrations on a user's **first run**, which is the worst possible moment |
| `-Semantic -Package` | The semantic-local optional dependency stack is installed and bundled deliberately rather than omitted by PyInstaller's lazy-import analysis | A package that lists local embeddings but cannot construct the local provider |
| Packaged security suite | Loopback-only binding *measured on a socket*, no CORS headers, the error envelope intact, traversal refused, and no developer material in the bundle | A property that holds in the source tree and not in the artifact. That gap is exactly where a packaging defect lives |
| `-Perf` | Refresh and preflight p95 against the semantic-local artifact, plus cold start, archive size, and semantic coverage after cold index | A deterministic-only performance number being mistaken for "embeddings enabled" |
| Earlier gates | Phases 0–6 still behave as their gates recorded | A semantic change that quietly moved older behavior |
| Manual install round trip | The install script's two changes and their two reversals, on a real user PATH | The one thing no test asserts, because asserting it means editing the developer's environment |

## The performance numbers, and how to read them

`docs/evaluation/phase-6-baseline-environment.md` holds the deterministic
packaged measurement with its hardware, method, and the fixed defects it found.
Phase 7 adds `scripts/measure_phase7_perf.py`, which writes
`docs/evaluation/baseline-phase-7-perf.json` when the semantic-local package can
be measured. If it writes `measurement_status: blocked` or exits 2, the Phase 7
packaging/performance gate is not satisfied in that environment.

## Known qualifications

These are stated at the gate rather than in a footnote, because a green run
should not hide them.

1. **Six browser tests are skipped on Chromium, across five spec files** —
   `onboarding-to-citation`, `preflight`, `restart-persistence`, `settings`,
   and `stream-reconnection` (×2). A browser defect, not application code;
   Firefox runs every one of them.

   *Counted from a gate run on 2026-08-10.* This said "four … on
   `/conversations/{id}`" and had already been corrected once, on 2026-08-07,
   for understating itself. **Count it from the run, do not copy it forward.**
2. ~~**Recovery does not detect pid reuse.**~~ **CLOSED 2026-08-10 by
   ADR-0037.** The owner stamp now records the owner's process start time, so a
   reassigned pid no longer keeps a dead run's repository blocked. Verified
   against the packaged binary with a live child process: correct start time →
   run left alone, wrong start time → run stranded.
3. **The executable is unsigned**, so SmartScreen warns on first run. Signing
   needs a certificate, which is a purchasing decision rather than an
   engineering one.

4. **Semantic-local packaging requires the heavy optional model stack.** The
   measured artifact is the onedir folder; `check_phase7.ps1 -Semantic -Package`
   passes `-SkipZip` because compressing the 1.05 GB tree exceeded the
   automation timeout in this workspace. If `semantic-local` is not installed
   or the package was built without `-SemanticLocal`, the Phase 7 perf script
   reports a blocked measurement rather than falling back to deterministic
   numbers.

5. **Two tracked artifacts hold CRLF in the working tree**:
   `baseline-phase-7-perf.json` (fixed 2026-08-10 — `measure_phase7_perf.py`
   used `write_text` without `newline=""`, so Python emitted CRLF on Windows
   into a *byte-gated* artifact) and **`baseline-phase-6.json`, which still
   does and was left alone.** Per ADR-0022 the remedy is `rm` + `git checkout
   --`, not a rewrite. It is not currently failing a gate, which is exactly why
   ADR-0022 warns about it: git reports a clean tree while the working file and
   the committed object disagree.

6. **The gate scripts themselves were unvalidated until 2026-08-10.** Three
   defects were found by running this document end to end for the first time:
   `check_phase7.ps1 -Package` could never bind its arguments (array splatting
   into an all-`[switch]` script — fixed, and guarded by
   `tests/unit/test_gate_script_invocations.py`); step 3 combined `-SkipWeb`
   with `-Perf` and returned 0 having measured nothing; step 4 looped over
   gates 1 and 2, which are frozen by design and always fail.

   The lesson is not the three defects. It is that **a validation checklist is
   itself untested code**, and this one had two steps that could not do what
   they claimed while the document described what each "proves".

A prior qualification stood here until 2026-07-29 — a server that stopped
answering under sustained change analysis, first misdiagnosed as a memory-fault
crash. It was uvicorn's access log blocking the event loop on an unread stdout
pipe, and it is fixed. The mistaken diagnosis is kept in
`docs/evaluation/phase-6-baseline-environment.md`, because how a wrong
conclusion survived six ruled-out hypotheses is worth more than a tidy record.
