# CodeAtlas

CodeAtlas is a local-first repository-intelligence and change-assurance layer.
The implementation follows the authoritative coding-agent contract exposed as
`AGENTS.md` / `CLAUDE.md` and the shared execution state in
`docs/plans/PLAN.md`.

## What works today (Phases 0-7 complete; post-gate polish in progress)

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
embedding migrations support cutover/rollback (`docs/operations/semantic-search.md`).

Post-gate provider work is now present behind explicit repository settings:
known OpenAI embedding model dimensions are resolved automatically, and local
embedding dimensions are reported as auto-detected when the model loads.
CodeAtlas does not download models for you — Settings names the answer model it
expects and shows the `ollama pull` command, which you run yourself. Optional
Ollama/OpenAI answer generation still does not change citations, line numbers,
claims, derivation, or confidence (`docs/operations/answer-generation.md`).

The Settings web surface has also been polished: a page header naming the
repository being configured, provider cards, summary panels, connection and
coverage panels, and clear warnings/limitations. The application shell is served
non-cacheable, because Vite asset names carry a content hash but `index.html` is
the pointer to whichever hashes are current — a cached shell keeps a browser on
the previous bundle after a rebuild.

A report of Settings "reverting" to an older view was traced on 2026-08-05 and
was **not** a caching problem. There are two built bundles, and the server picks
between them by launch mode: a source checkout serves `apps/web/dist`, the
packaged executable serves its own copy under `dist/codeatlas-win64/`. A package
built before a UI change keeps serving the older interface until it is rebuilt.
**Rebuild the package whenever the web application changes**
(`scripts/build_package.ps1`).

`codeatlas serve --ephemeral` starts from empty storage and discards it when the
server stops, so indexing, embeddings, and conversations are all fresh each run
while history behaves normally within the run. It never opens the real database,
an explicit `--db` outranks it, and `CODEATLAS_EPHEMERAL_REPOSITORIES` names the
repositories to register and index at startup (ADR-0013,
`docs/operations/ephemeral-sessions.md`).

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

## Running the project

Everything below is PowerShell on Windows. Each command is explained, because
several of them exist for a reason that is not obvious from the name.

### Step 0 — Install, once

Prerequisites: Windows 11, PowerShell 7 or Windows PowerShell 5.1, `uv`,
Node.js 20+ with pnpm (`corepack enable pnpm`), and Git on `PATH`. Git is not
optional — change preflight shells out to it through an argument-array
subprocess.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
```

Installs the locked Python environment and the `apps/web` dependencies. It syncs
**frozen**, so you get exactly the versions in `uv.lock` and `pnpm-lock.yaml`
rather than whatever resolves today. The `-ExecutionPolicy Bypass -File` form is
required; a plain `./script.ps1` is blocked by the default execution policy.

Optional extras — skip both unless you actually want semantic recall.
Deterministic behaviour never needs them:

```powershell
uv sync --extra semantic-local      # local embeddings via sentence-transformers; ~1 GB of torch, nothing leaves the machine
uv sync --extra semantic-openai     # OpenAI embeddings; transmits, and needs OPENAI_API_KEY
```

Configuration lives in `.env` **in this project folder**, copied from
`.env.example`. It is deliberately not read from the directory you run the
command in: a repository you index must never be able to configure the tool
indexing it. Every setting in it is optional, and putting an API key there
enables nothing on its own — a provider is granted permission per repository, in
Settings.

Since ADR-0015 the OpenAI key can also be entered **in Settings**, where it is
stored in the Windows Credential Manager rather than a plaintext file. A key
saved there outranks `.env`, no response ever returns it, and a backup does not
carry it — restoring onto another machine means entering it again.

### Step 1 — Start the app

```powershell
uv run codeatlas serve --web --open
```

The normal way to run CodeAtlas, and exactly what a packaged build does. One
loopback server on `http://127.0.0.1:8000` serves both the built web app and the
`/v1` API, so the browser sees a single origin — which is what lets the API stay
loopback-bound with no CORS relaxation. Breaking the flags apart:

- `--web` also serves `apps/web/dist`. If that build is missing the command
  refuses with `INVALID_REQUEST` and tells you to run
  `pnpm --dir apps/web build`, rather than handing you a blank page.
- `--open` launches a browser. Without it the URL is only printed — starting a
  server should not steal focus, and must not try to on a headless machine.
- `--host` accepts loopback addresses only. Anything else exits with
  `INVALID_REQUEST`, because binding wider needs authentication and a CORS
  review that this product has not had.
- `--port 8000` is the default; change it if the port is taken.

Two variants worth knowing:

```powershell
uv run codeatlas serve                    # API only, no web assets
uv run codeatlas serve --web --ephemeral  # fresh empty storage, discarded when the server stops
```

`--ephemeral` (ADR-0013) gives you a clean index, clean embeddings, and clean
conversations every run, while history still behaves normally *within* the run.
It never opens the real database, an explicit `--db` outranks it, and
`CODEATLAS_EPHEMERAL_REPOSITORIES` names repositories to register and index at
startup. Every ephemeral run pays a full index — there is no reuse, which is
inherent to asking for freshness.

### Step 2 — Use it from the CLI

Same application services as the web app, so results are identical.

```powershell
uv run codeatlas repo add C:\path\to\repository --json
```

Registers a repository. It only records the path and Git state; it does not read
the code yet. `--json` prints the machine-readable envelope, including the
`repository_id` every later command needs.

```powershell
uv run codeatlas index <repository_id>
```

Scans, parses, extracts symbols and relations, chunks, and builds the search
index — then validates all of it and activates the snapshot in a single atomic
transaction. An interrupted index leaves the previous active snapshot usable.
Repository code is never imported, built, or executed.

```powershell
uv run codeatlas symbol <repository_id> PaymentService.capture
uv run codeatlas search text <repository_id> "idempotency key"
uv run codeatlas graph callers <repository_id> PaymentService.capture
```

Exact symbol lookup, lexical (FTS5) text search, and bounded graph traversal.
All three are deterministic and need no model. Each answer names the snapshot it
came from, and abstains rather than guessing when nothing matches.

```powershell
uv run codeatlas impact <repository_id>
uv run codeatlas impact <repository_id> --commits HEAD~1..HEAD --format sarif
```

Change preflight — the point of the product. With no arguments it compares your
working tree against `HEAD`; `--commits` takes a range instead. Output is JSON
by default, with `--format markdown` for humans and `--format sarif` for
scanners. Base-side evidence is labelled historical.

```powershell
uv run codeatlas repo watch <repository_id>
uv run codeatlas doctor
uv run codeatlas backup / restore
```

`repo watch` keeps the index current without an explicit `index`, debounced, and
disableable per repository — filesystem events name candidates, never truth, so
a reconciling scan and the content hashes always decide. `doctor` reports what
was interrupted, what is blocking a reindex, and what was never indexed, telling
those apart because the remedies differ. `backup` copies the database safely
while the server runs; `restore` validates integrity and schema version *before*
replacing anything, and keeps what it replaced.

### Step 3 — Frontend dev loop (only when editing `apps/web`)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_dev.ps1
```

Starts uvicorn on 8000 and the Vite dev server in front of it, with `/v1`
proxied so the browser still talks to one origin. Two processes because they
are genuinely two servers. The script stops the API when you exit Vite, so no
stray process holds the port. `-ApiOnly` runs the backend alone; `-ApiPort`
moves it.

If you change a REST endpoint, regenerate the frontend types — never hand-edit
them:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/generate_web_types.ps1
```

### Step 4 — Run the packaged build

```powershell
dist\codeatlas-win64\codeatlas.exe serve --web --open
```

Unzip and run; no install, no elevation. Rebuild it with
`scripts/build_package.ps1`. The executable is **unsigned**, so SmartScreen
warns on first run — a declared, accepted gap that needs a purchased
certificate.

### Step 5 — Verify before calling anything done

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync -SkipE2E
```

The quality gate: contract schema, Python tests, Ruff, strict MyPy, the
evaluation corpus, the tracked Phase 0/3/4 baselines, and the web app's lint,
types, component tests, and build. `-SkipSync` reuses the installed environment
instead of re-syncing. Unlike earlier phase scripts this one runs the Playwright
suites **inside** the gate; `-SkipE2E` opts out for a fast inner loop.

### If something does not work

| Symptom                                                     | Cause and fix                                                                                                         |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `INVALID_REQUEST: the web application has not been built` | `pnpm --dir apps/web build`, or use the packaged release                                                            |
| `--host must be a loopback address`                       | Loopback only, by design. Use`127.0.0.1`                                                                            |
| Port already in use                                         | `--port` on `serve`, `-ApiPort` on `run_dev.ps1`                                                              |
| Script will not run                                         | Use the`-ExecutionPolicy Bypass -File` form                                                                         |
| A repository will not reindex                               | `codeatlas doctor` names the blocking run and its pid                                                               |
| The UI looks older than the code                            | You are almost certainly running the packaged build. Rebuild it with`scripts/build_package.ps1`, or run from source |

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
