# Windows release validation

What to run before calling a build releasable, and — just as important — what
each step actually proves. A checklist whose items are not understood is a
ritual, and rituals pass while products break.

Everything here targets the **packaged artifact**. Phases 0–5 measured a source
checkout, which is the right thing to measure while building and the wrong thing
to ship.

## The sequence

```powershell
# 1. Everything, including the browser suites, the packaged build, and the
#    packaged smoke and security tests.
powershell -ExecutionPolicy Bypass -File scripts/check_phase6.ps1 -Package

# 2. The Section 19.3 performance targets, on the artifact just built.
powershell -ExecutionPolicy Bypass -File scripts/check_phase6.ps1 -SkipSync -Perf

# 3. The earlier gates, unchanged.
foreach ($n in 0..5) {
    powershell -ExecutionPolicy Bypass -File "scripts/check_phase$n.ps1" -SkipSync
}

# 4. Install, upgrade, and uninstall, by hand, once.
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
codeatlas doctor
codeatlas serve --web --open
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Uninstall
```

## What each step proves

| Step | Proves | Would otherwise hide |
| --- | --- | --- |
| `-Package` | The binary starts, migrates a fresh database from *bundled* migrations, indexes and resolves a symbol with evidence, serves the SPA and `/v1` on one origin, and upgrades a database written by a real earlier build | A missing data file — migrations and web assets are not modules, so PyInstaller does not find them by analysis. Both fail late: the migrations on a user's **first run**, which is the worst possible moment |
| Packaged security suite | Loopback-only binding *measured on a socket*, no CORS headers, the error envelope intact, traversal refused, and no developer material in the bundle | A property that holds in the source tree and not in the artifact. That gap is exactly where a packaging defect lives |
| `-Perf` | Refresh and preflight p95 against the artifact, plus cold start | A regression that a source-checkout measurement would not see, and the packaging cost of a frozen interpreter |
| Earlier gates | Phases 0–5 still behave as their gates recorded | A hardening change that quietly moved older behavior |
| Manual install round trip | The install script's two changes and their two reversals, on a real user PATH | The one thing no test asserts, because asserting it means editing the developer's environment |

## The performance numbers, and how to read them

`docs/evaluation/phase-6-baseline-environment.md` holds the recorded measurement
with its hardware, method, and — deliberately in the same document — the one
open defect the measurement found. Section 19.3 requires performance claims to
name hardware, repository profile, cold/warm state, and method; that document is
where they are named.

## Known qualifications

These are stated at the gate rather than in a footnote, because a green run
should not hide them.

1. **Four conversation-route browser tests are skipped on Chromium**, whose
   renderer crashes navigating to `/conversations/{id}`. A browser defect, not
   application code; Firefox proves all seven.
2. **Recovery does not detect pid reuse.** If a dead run's pid is reassigned
   before the next start, that repository stays blocked from reindexing.
   `codeatlas doctor` names the run and its pid, so it is visible rather than
   silent, but it is not automatic.
3. **The executable is unsigned**, so SmartScreen warns on first run. Signing
   needs a certificate, which is a purchasing decision rather than an
   engineering one.

A fourth qualification stood here until 2026-07-29 — a server that stopped
answering under sustained change analysis, first misdiagnosed as a memory-fault
crash. It was uvicorn's access log blocking the event loop on an unread stdout
pipe, and it is fixed. The mistaken diagnosis is kept in
`docs/evaluation/phase-6-baseline-environment.md`, because how a wrong
conclusion survived six ruled-out hypotheses is worth more than a tidy record.
