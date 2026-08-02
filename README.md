
# CodeAtlas

CodeAtlas is a local-first repository-intelligence and change-assurance layer.
The implementation follows the authoritative coding-agent contract exposed as
`AGENTS.md` / `CLAUDE.md` and the shared execution state in
`docs/plans/PLAN.md`.

## What works today (Phases 0–6 complete; Phase 7 in progress)

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

Installing a newer build upgrades the database on first open, and writes a
verified checkpoint beside it before any migration runs — `codeatlas upgrade`
does the same thing deliberately and says what it preserved. An *older* build
pointed at a newer database refuses rather than answering from a schema it has
never seen. The path is tested from a database written by a real earlier build
(`docs/operations/upgrade-and-migration.md`).

Performance and security are verified on the packaged artifact rather than a
source checkout: refresh p95 1.30 s and change-preflight p95 3.10 s against the
binary, and a security suite that drives the real executable
(`docs/operations/release-validation.md`). That validation found three defects,
all now fixed — including a server that stopped answering under sustained load,
which took a wrong diagnosis before the right one
(`docs/evaluation/phase-6-baseline-environment.md`).

Phase 7 adds optional semantic retrieval. The default provider is still `none`;
deterministic behavior does not need an embedding model. Repositories can opt
into local embeddings or governed OpenAI embeddings through the settings
surface, semantic coverage is reported per active snapshot, and shadow
embedding migrations support cutover/rollback. Reranking and generated
explanations have seams and validation but are recorded as declined until a real
provider shows measured uplift (`docs/operations/semantic-search.md`).

Phase 7 packaged semantic-local performance has been measured on the onedir
artifact: refresh p95 0.975 s, preflight p95 2.298 s, semantic coverage 1.0,
and package tree size 1.05 GB.

The Phase 7 gate was approved on 2026-07-31, **with one target recorded as
missed**: primary evidence Recall@10 is 0.6667 against a ≥ 0.90 target. The
semantic layer moves that number in the right direction, and the target is
missed with and without it — read
`docs/evaluation/phase-7-baseline-environment.md` before quoting either figure.
That completes Phases 0–7; `docs/plans/PLAN.md` is the live phase and task
status.

## Windows development

Requirements: Windows 11, PowerShell 7 or Windows PowerShell 5.1, `uv`, and
— from Phase 5 onward — Node.js 20+ with pnpm (`corepack enable pnpm`) for
the web application in `apps/web`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
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
- `docs/operations/upgrade-and-migration.md` — upgrading, the checkpoint, and the refusal
- `docs/operations/release-validation.md` — what to run before a release, and what each step proves
- `docs/operations/end-to-end-tests.md` — the Playwright harness and what each suite proves
- `docs/operations/semantic-search.md` — semantic providers, coverage, migrations, and admission state
- `docs/operations/answer-generation.md` — optional written explanations, the models, and every failure message
- `docs/adr/README.md` — the eight accepted architecture decisions
- `docs/evaluation/phase-4-baseline-environment.md` — how to read the baseline and performance numbers
- `docs/evaluation/phase-6-baseline-environment.md` — packaged performance and fixed release defects
- `docs/evaluation/phase-7-baseline-environment.md` — semantic uplift measurement and its limits
- `docs/evaluation/phase-7-performance-environment.md` — semantic-local package/perf method and measured results
- `docs/security/threat-model.md` — controls and their enforcement status
