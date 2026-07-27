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

Chromium only. Firefox and WebKit are untested, and the suites cover the three
workflows Phase 5 deferred rather than the whole of Section 14 — P6-08 may
propose widening that now the harness exists.

The stream suite proves the transport contract as a browser sees it. It does not
prove the conversation UI reconnects mid-run, because submission runs inline and
the UI opens no stream; see the Phase 6 plan for the decision that blocks it.
