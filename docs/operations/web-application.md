# Web Application

Status: current as of 2026-08-04
Audience: developers running or extending `apps/web`

## Running it

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_dev.ps1
```

`run_dev.ps1` starts the API on loopback and the Vite dev server in front of
it, and stops the API it started. Vite proxies `/v1` to the API, so the browser
sees one origin and the API keeps its loopback-only, no-CORS posture. Node 20+
and pnpm are prerequisites.

The gate is `scripts/check_phase5.ps1` — backend first, then generated types,
then web lint, types, tests, and build.

For the production-style local app, use the same command users run:

```powershell
uv run codeatlas serve --web --open
```

That serves the built `apps/web/dist` bundle from FastAPI on
`http://127.0.0.1:8000`. The application shell is returned with
`Cache-Control: no-store, max-age=0, must-revalidate` so a rebuilt local bundle
does not keep pointing a browser tab at stale asset hashes.

## What it does

- **Repository onboarding** — add a local repository, watch real index status,
  read diagnostics. Every number comes from `/v1/repositories/*`; nothing
  simulates progress, and a skeleton stands only for a request in flight.
- **Conversations** — a sidebar grouped by the backend's own timestamps, with
  search, rename, archive, and delete. The URL identifies the active thread.
- **Thread** — submit a question, see the answer, retry a failed or cancelled
  one. Assistant text renders only through the sanitizer.
- **Evidence** — a citation opens a drawer showing path, symbol, line range,
  derivation, confidence, and **the snapshot the answer used**, with the
  excerpt as text.
- **Change preflight** — runs a working-tree analysis and renders the persisted
  report, findings grouped by severity, warnings and limitations visible.
- **Settings** — `/settings`, reached from the sidebar header. Chooses the
  embedding and answer providers for **one** repository: the active one, which
  the page names rather than implies, because this is the only screen that can
  cause repository content to leave the machine. The current surface uses
  provider cards, summary panels, explicit transmission badges, connection and
  coverage panels, fresh settings/model refetch on mount, and an Ollama
  **Download model** action for the typed answer model. With no repository
  selected it links back to the home page, where that choice is made; the
  repository selector is not duplicated onto this route.

## Architecture

| Concern | Choice |
| --- | --- |
| Build | Vite + React 18 + TypeScript strict (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) |
| Styling | Tailwind 4 with CSS custom-property tokens |
| Server state | TanStack Query; the server is the source of truth |
| Routing | react-router; `/conversations/:conversationId`, `/settings` |
| API types | generated from the live OpenAPI schema, checked in, `--check` gated |
| Markdown | `react-markdown` + `rehype-sanitize`, **no `rehype-raw`** |
| Tests | Vitest + Testing Library + `vitest-axe` |

## The rules that are not negotiable

1. **Repository content is data in the browser too.** Raw HTML never enters the
   tree, link protocols are limited to `http`/`https`/`mailto`, and evidence
   excerpts render inside `<pre><code>` as text. Ten tests cover the specific
   vectors.
2. **The server is authoritative.** Optimistic UI shows a submitted question
   immediately, then drops the placeholder when the server's rows arrive —
   reconciled by ID, never merged.
3. **A message keeps its own snapshot label.** An answer produced against a
   superseded snapshot says so; it never borrows the current one.
4. **Evidence that cannot be verified is not shown.** A hash mismatch or a
   missing row produces an explicit refusal, not current file contents under an
   old citation.
5. **Never color alone.** Freshness, severity, and error states all carry text.
6. **No fabricated progress.** Status lines name stages the pipeline actually
   reported.

## What the web application does not do

- **No LLM authority.** Every factual claim still comes from deterministic or
  validated retrieval. Optional answer generation may write prose above the
  verified result, but it cannot change citations, line numbers, claims,
  derivation, or confidence.
- ~~**Answering is synchronous.**~~ **Closed by P6-STREAM (ADR-0008).**
  `POST /v1/conversations/{id}/messages` now returns `202` with a queued run and
  answers on a worker. The thread opens the run's stream, renders
  `generation.delta`, and reads the persisted message when the run terminates —
  so cancellation has a real window and the live path is exercised rather than
  merely implemented. The channel is opened by the submitting request *before*
  it responds, so a client may open the stream immediately without racing the
  worker.
- ~~**No Playwright suites.**~~ **Closed by P6-01 and P6-STREAM.** Seven browser
  tests run on Firefox and Chromium. Four are skipped on Chromium only: its
  renderer crashes on client-side navigation to a conversation route, which is a
  browser defect rather than application code (Firefox passes all seven; the
  isolation table is in the 2026-07-28 handoff in `docs/plans/PLAN.md`).
- **No message pagination in the UI.** The backend pages; the thread fetches
  the first page only.
- **No "purge now" control** for soft-deleted conversations; retention is
  Phase 6.
- ~~**`codeatlas serve --web` is not built.**~~ **Closed by Phase 6.** The
  packaged/source `serve --web` path serves the built web app and `/v1` from
  one loopback origin. On 2026-08-04 the exact
  `uv run codeatlas serve --web --open` path was probed: `/settings` returned
  the current shell, cache headers were `no-store`, and the served bundle
  contained the new Settings UI. A user browser session still showed the older
  Settings view until reload; that observation is recorded as environment
  specific in `docs/plans/PLAN.md`.
