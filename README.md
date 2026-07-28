# CodeAtlas

CodeAtlas is a local-first repository-intelligence and change-assurance layer.
The implementation follows the authoritative requirements in `CLAUDE.md` and
the shared execution state in `docs/plans/PLAN.md`.

## What works today (Phases 0–5 complete; Phase 6 in progress)

Register a local repository, index Python/TypeScript/JavaScript into a
validated snapshot with a cross-file relation graph, search it, traverse it,
and run change preflight — through the application services, the `/v1` REST
API, the CLI, and MCP, all sharing one implementation.

```powershell
uv run codeatlas repo add C:\path\to\repository --json
uv run codeatlas index <repository_id>
uv run codeatlas symbol <repository_id> PaymentService.capture
uv run codeatlas search text <repository_id> "idempotency key"
uv run codeatlas graph callers <repository_id> PaymentService.capture
uv run codeatlas impact <repository_id>            # working tree vs HEAD
uv run codeatlas impact <repository_id> --commits HEAD~1..HEAD --format sarif
```

Change preflight reports changed files and symbols, bounded impact paths,
related tests and documents, architecture-rule violations, and risk-ordered
findings — every finding citing hash-verified file-and-line evidence, with
base-side evidence labeled historical. See
`docs/operations/change-analysis.md`.

Every answer is bound to a snapshot. If a file changed after indexing, CodeAtlas
withholds the evidence and says so rather than citing content that no longer
matches. If nothing matches, it abstains rather than guessing.

The web application in `apps/web` adds persistent conversations, an evidence
drawer, and change preflight — see `docs/operations/web-application.md`. It
answers deterministically: there is no LLM, and an unanswerable question
produces an explicit abstention.

A filesystem watcher keeps the index current without an explicit `index`
command, debounced and disableable per repository
(`codeatlas repo watch`, `docs/operations/continuous-freshness.md`). A periodic
reconciling scan, plus an immediate catch-up at startup, covers what the event
stream can silently lose — events name candidates, never truth, so the scan
and the content hashes always decide.

Asking a question is accept-then-stream: the request returns `202` with a queued
run, the answer is computed on a worker, and the thread follows it over
Server-Sent Events — so a long answer never holds a request open, cancelling
reaches a run that is genuinely executing, and a reload recovers the persisted
answer with its citations and the snapshot it used (ADR-0008).

A process killed mid-index is healed on the next start, and the repository says
so: `codeatlas doctor` reports what was interrupted, what is blocking a reindex,
and which repositories were never indexed at all — telling those apart, because
the remedies differ (`docs/operations/crash-recovery.md`). Recovery leaves a run
alone while the process that owns it is still alive, so it never interrupts an
index the watcher is in the middle of.

`codeatlas backup` copies the database safely while CodeAtlas is running, and
`codeatlas restore` validates a backup's integrity and schema version *before*
replacing anything, keeping the database it replaced. Removing a repository
never touches source files and refuses to take conversations with it unless
asked (`docs/operations/backup-and-restore.md`).

CodeAtlas packages as a Windows build you unzip and run: `codeatlas serve --web`
starts the API and serves the web application from the same origin, so the
browser needs no CORS relaxation and the API stays loopback-bound
(`docs/operations/packaging-and-install.md`).

Not built yet: the upgrade workflow from a previous version, and performance and
security re-verified on the packaged artifact (both Phase 6); and embeddings or
any model provider (Phase 7). `docs/plans/PLAN.md` is the live phase and task
status.

## Windows development

Requirements: Windows 11, PowerShell 7 or Windows PowerShell 5.1, `uv`, and
— from Phase 5 onward — Node.js 20+ with pnpm (`corepack enable pnpm`) for
the web application in `apps/web`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/check_phase6.ps1 -SkipSync
```

The quality command validates the tracked contract schema, the Python tests,
lint, types, the evaluation corpus, the tracked Phase 0/3/4 baselines, and the
web app's lint, types, component tests, and build. Unlike its predecessors it
also runs the Playwright end-to-end suites **inside** the gate rather than
beside it; `-SkipE2E` opts out for a fast inner loop. Repository fixtures are
untrusted data and are never imported, built, or executed.

- `docs/operations/development-windows.md` — setup and the Phase 0 gate
- `docs/operations/development-windows-phase1.md` — CLI, API, and Windows behavior
- `docs/operations/relations-and-graph.md` — the relation graph and traversal
- `docs/operations/change-analysis.md` — change preflight and its limits
- `docs/operations/web-application.md` — the web app, its rules, and its limits
- `docs/operations/continuous-freshness.md` — the watcher, its debounce, and its switch
- `docs/operations/crash-recovery.md` — what a kill leaves behind, and `codeatlas doctor`
- `docs/operations/backup-and-restore.md` — backup, restore, deletion, and retention
- `docs/operations/packaging-and-install.md` — building, installing, and `serve --web`
- `docs/operations/end-to-end-tests.md` — the Playwright harness and what each suite proves
- `docs/adr/README.md` — the eight accepted architecture decisions
- `docs/evaluation/phase-4-baseline-environment.md` — how to read the baseline and performance numbers
- `docs/security/threat-model.md` — controls and their enforcement status
