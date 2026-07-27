# Web Application (Phase 5)

Status: current as of Phase 5
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

## Architecture

| Concern | Choice |
| --- | --- |
| Build | Vite + React 18 + TypeScript strict (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) |
| Styling | Tailwind 4 with CSS custom-property tokens |
| Server state | TanStack Query; the server is the source of truth |
| Routing | react-router; `/conversations/:conversationId` |
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

## What Phase 5 does not do

- **No LLM.** Every assistant message is a deterministic answer or an explicit
  abstention. Generation is Phase 7, behind its own gate.
- **Answering is synchronous**, so the stream always serves from the replay
  buffer and cancellation has no realistic window over HTTP. The live path is
  implemented and unit-tested; a background executor would exercise it.
- **No Playwright suites.** The gate conditions that need a real browser —
  restart persistence, reconnect mid-stream — are covered at the component and
  backend layers but not end to end.
- **No message pagination in the UI.** The backend pages; the thread fetches
  the first page only.
- **No "purge now" control** for soft-deleted conversations; retention is
  Phase 6.
- **`codeatlas serve --web` is not built.** Development runs two servers.
