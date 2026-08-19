# Running the end-to-end suites

The browser suites drive the real application: a real repository on disk, a real
index, the real API on loopback, and the built SPA. Nothing is stubbed.

## One-time setup

```powershell
cd apps/web
pnpm install
pnpm exec playwright install chromium
```

The browser download is roughly 300 MB and is cached per user, not per
checkout.

## Running

```powershell
cd apps/web
pnpm exec vite build      # the suites serve `dist`, not the dev server
pnpm exec playwright test
```

Or as part of the phase gate, which builds first and runs these last:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase6.ps1 -SkipSync
```

Use `-SkipE2E` for a fast inner loop. The gate is the place the suites are
required to pass.

## How it fits together

| Piece | Role |
| --- | --- |
| `scripts/e2e_backend.py seed` | Creates the fixture repositories and indexes one of them. Prints JSON describing what it made. |
| `scripts/e2e_backend.py serve` | Serves one database on loopback. Disposable and restartable. |
| `e2e/support/backend.ts` | Spawns, stops, and restarts that server from inside the test worker. |
| `e2e/support/fixtures.ts` | Seeds once per worker and guarantees the server is running for every test. |
| `vite preview` | Serves the built app and proxies `/v1` to the harness backend. |

Seeding and serving are separate commands on purpose: the restart-persistence
suite kills the API and starts it again against the *same* database, which is
only possible when creating that database is not part of starting the server.

The API is never told about the browser. It stays loopback-bound with no CORS
middleware, exactly as it ships; the preview server's proxy is what puts them on
one origin.

`codeatlas serve --web` — the packaged launcher — is P6-06. This harness is not
it, and deliberately so: suites that exercise an entry point invented for them
prove less than suites that exercise the one users run.

## What each suite proves

| Suite | What it proves |
| --- | --- |
| `onboarding-to-citation.spec.ts` | The critical workflow: add a repository, index it, ask a question, open the evidence behind the answer. |
| `restart-persistence.spec.ts` | Conversations and messages survive a real process kill and come back from the server, not a client cache. |
| `stream-reconnection.spec.ts` | The typed SSE contract as a browser sees it: named frames, gapless sequences, resumption, and citations restored after a reload. |
| `settings.spec.ts` | The settings route against the real API: the provider list and each provider's availability, `POST /v1/models/test` reporting `PROVIDER_DISABLED`, a `PATCH` that survives a reload, and — with a transmitting policy set through the API — the warning, the stored budget, and real coverage numbers. |

The settings suite reaches the transmitting rendering by loading `/settings`
directly rather than clicking into it, because Chromium kills its renderer when
a *client-side* navigation mounts that branch.

> **The second half of this paragraph was measured false on 2026-08-19 and is
> corrected here.** It used to read "the identical tree renders correctly on a
> full page load on both engines". It does not. `settings.spec.ts:248` uses
> `page.goto("/settings")` — a full document navigation — and **Chromium's
> renderer still crashes**, deterministically: five runs from a clean state, in
> isolation and in the full suite, headed and headless, against a freshly built
> bundle. Firefox renders the same tree correctly.
>
> **A full page load is therefore not a workaround for this branch**, only for
> the conversation routes. The reproduction and the ruled-out hypotheses are the
> Deferred Register row in `docs/plans/PLAN.md`.

The transmitting policy is set on whichever repository a fresh load will show,
and restored in a `finally` block — the database outlives the test.

## Debugging a failure

Backend request logs land in `.e2e-tmp/api.log`, next to the fixture database,
and are wiped at the start of each run. They answer the first question a failing
browser test raises — what did the page ask for, and what did it get — without
re-running with instrumentation added by hand.

Playwright writes a trace for each failure:

```powershell
pnpm exec playwright show-trace test-results/<test-dir>/trace.zip
```

`.e2e-tmp/` is disposable. Deleting it costs one reseed.

## Scope

Chromium and Firefox; WebKit is untested. The suites cover the three workflows
Phase 5 deferred plus the settings route, rather than the whole of Section 14.

Tests are skipped on Chromium wherever its renderer crashes
(`e2e/support/chromium-crash.ts`); Firefox proves all of them. A clean full run
on 2026-08-19 counted **seven skipped, three passed, and one failed** — count it
from the run rather than copying a number forward, which this document has
already had to correct once.

**The one failure is `settings.spec.ts:248`, and it is not skipped.** It used to
be described here as needing no skip because it avoids client-side navigation.
That reasoning was measured false: the crash reaches it through a full document
navigation too, so the suite has an unskipped test failing on a browser defect.
**Whether it joins the skip helper is a decision, not a cleanup** — this project
forbids skipping a test to make a build pass, so it is recorded in the Deferred
Register with its reproduction rather than quietly silenced.

The stream suite proves the transport contract as a browser sees it. It does not
prove the conversation UI reconnects mid-run, because submission runs inline and
the UI opens no stream; see the Phase 6 plan for the decision that blocks it.
