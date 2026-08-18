# CodeAtlas

**A local-first repository-intelligence and change-assurance layer.** It tells
you what changed, what may be affected, and what evidence proves it — with every
material claim citing a real file, symbol, and line range in a named snapshot of
your repository.

Source never leaves your machine unless you explicitly enable a provider for a
specific repository. Nothing here treats a language model as repository truth.

| | |
| --- | --- |
| **Status** | Phases 0–7 complete, every gate user-approved; project closed out 2026-08-10, post-gate work ongoing |
| **Platform** | Windows 11 primary (loopback only, single user) |
| **Languages indexed** | Python, TypeScript, JavaScript, **Java**, **Go**, **Rust**, **Scala**, Markdown, common config/schema formats |
| **Contract version** | `1.1` · **Schema version** `14` (migrations `0001`–`0014`) · **MCP tool schema** `1.0` |
| **Tests** | 2252 passing at the last full gate run |
| **Authority** | `AGENTS.md` is the release-blocking contract · `docs/plans/PLAN.md` is live status |

---

## Contents

1. [The problem](#the-problem)
2. [What CodeAtlas does](#what-codeatlas-does)
3. [The trust contract](#the-trust-contract)
4. [Quick start](#quick-start)
5. [Features](#features)
6. [How it works](#how-it-works)
7. [The four surfaces](#the-four-surfaces)
8. [Configuration and optional providers](#configuration-and-optional-providers)
9. [Operating it](#operating-it)
10. [Security and privacy](#security-and-privacy)
11. [Measured results and known limits](#measured-results-and-known-limits)
12. [Developing CodeAtlas](#developing-codeatlas)
13. [Documentation map](#documentation-map)

---

## The problem

Before you submit a change, you have to guess what it might break. The answers
are scattered across the diff, the test suite, the import graph, a
half-remembered architecture rule, and whatever a teammate happens to know.

Asking an AI assistant instead is faster but worse: it will confidently name a
file that does not exist, cite a line that moved three commits ago, or explain a
function it never read. You end up doing the verification work anyway, now with
extra text to disprove.

CodeAtlas answers with evidence attached — real paths, real line ranges, from a
known snapshot — and says **"I don't know"** when it does not know. An
abstention is a successful outcome here, not a failure.

## What CodeAtlas does

It exists to answer five questions:

1. **What changed?**
2. **What may be affected?**
3. **What evidence proves it?**
4. **How current is that evidence?**
5. **What does CodeAtlas not know?**

The flagship workflow is **change preflight**: point it at your working tree or a
commit range and get the changed symbols, what depends on them, the affected
tests and documents, the configuration and schema keys involved, and the
architecture rules the change crosses — risk-ordered, every finding citing
hash-verified evidence.

**Who it is for**

- **The developer about to commit** — a second opinion before pushing.
- **The reviewer opening someone else's diff** — blast radius for code they did
  not write, when the PR description says "small refactor".
- **A coding agent working in the repository** — facts it can act on over MCP,
  and a way to tell a resolved fact from a guess.

**What it is not:** not an IDE, not an autonomous code editor, not "chat with
your codebase", not a replacement for compilers, language servers, tests, SAST,
SCA, or CI, and not cloud-first. There is no multi-user tenancy, no RBAC, no
billing, and no GitHub/GitLab or CI integration.

## The trust contract

This is the part that shapes every other decision in the codebase.

| Rule | What it means in practice |
| --- | --- |
| **Evidence or abstention** | Every material factual claim carries evidence IDs that resolve to a file, symbol, and line range in the selected snapshot. Missing or invalid evidence causes rejection, a warning, or explicit abstention — never invention. |
| **Deterministic before probabilistic** | Exact lookup, parsing, Git diff mapping, graph traversal, architecture rules, test links, and evidence validation never depend on a model. Provider failure, timeout, or exhausted budget degrades to a useful deterministic result. |
| **Structured findings are authoritative** | Natural-language prose is a *derived view*. A model may explain evidence; it may not change a citation, a line number, a derivation, or a confidence score. |
| **Snapshot-bound** | Every query names its repository and snapshot. Active results never contain entities from another snapshot. A historical citation keeps its historical snapshot label rather than being silently relabelled as current. |
| **Stale evidence is withheld** | If a file changed after indexing, CodeAtlas withholds the excerpt and says so rather than showing content that no longer matches the claim. |
| **Repository content is untrusted input** | Code, comments, documents, filenames, and metadata are data — never instructions to the application or to a model. Indexing never imports, builds, tests, or executes anything. |

### The derivation ladder

`derivation` and `confidence` are **separate fields**. A high score is not a
promotion — this enum is the spine of the product.

| Class | May support |
| --- | --- |
| `deterministic` | an authoritative finding |
| `static_resolved` | a finding, with stated language limitations |
| `high_confidence_heuristic` | a labeled heuristic finding |
| `low_confidence_heuristic` | advisory discovery only |
| `semantic_candidate` | a candidate only, never a fact |
| `model_generated` | narrative only |
| `unsupported` | nothing — must abstain |

---

## Quick start

Prerequisites: Windows 11, PowerShell 7 or Windows PowerShell 5.1, [`uv`],
Node.js 20+ with pnpm (`corepack enable pnpm`), and Git on `PATH`. Git is not
optional — change preflight shells out to it through an argument-array
subprocess.

```powershell
# 1. Install the locked environment (frozen: exactly uv.lock and pnpm-lock.yaml)
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1

# 2. Register and index a repository
uv run codeatlas repo add C:\path\to\repository --json   # prints repository_id
uv run codeatlas index <repository_id>

# 3. Ask it something
uv run codeatlas symbol <repository_id> PaymentService.capture
uv run codeatlas callers <repository_id> PaymentService.capture
uv run codeatlas impact <repository_id>

# 4. Or use the web app — API and UI on one loopback origin
uv run codeatlas serve --web --open
```

`repo add` only records the path and Git state; it does not read your code until
you run `index`. No source is executed at any point.

Optional extras — **skip both** unless you want semantic recall. Deterministic
behaviour never needs them:

```powershell
uv sync --extra semantic-local    # local embeddings; ~1 GB of torch, transmits nothing
uv sync --extra semantic-openai   # OpenAI embeddings; transmits, needs a key and a budget
```

[`uv`]: https://docs.astral.sh/uv/

---

## Features

### Repository truth

- **Windows-safe registration and scanning.** Paths are canonicalized and
  confirmed inside the approved root. Symlinks, junctions, traversal, reserved
  names, long paths, UNC paths, oversized files, deep trees, binaries, and
  invalid Unicode are all handled explicitly rather than crashing or escaping.
- **Snapshots as the unit of truth.** Exactly one snapshot is active per
  repository. Work is built in staging, validated (entity membership, FTS rows,
  relation endpoints, evidence ranges, version metadata), and activated in a
  single atomic transaction. An interrupted index leaves the previous active
  snapshot fully usable.
- **Incremental by content hash.** A one-symbol edit recomputes only the
  affected files, symbols, relations, chunks, and FTS projections; unchanged
  content reuses its existing chunk and embedding rows.
- **Symbol extraction** via Tree-sitter with Python `ast` enrichment, plus
  TypeScript/JavaScript parsing, Markdown sections, and nested configuration
  keys as addressable symbols.

### Retrieval

- **Exact symbol and path resolution** — `codeatlas symbol`, deterministic,
  no model, validated file-and-line evidence.
- **Lexical search** over FTS5 — text, file paths, or symbol names. User text is
  treated as data, never as FTS syntax.
- **Bounded graph traversal** — callers, callees, dependencies, exports, related
  tests, related documents, and traced flows, with depth and visited-node limits
  and explicit truncation warnings.
- **Git-aware retrieval** for change questions.
- **Optional semantic candidates** for conceptual questions, fused by rank
  without erasing derivation, and always labelled `semantic_candidate`.

The relation graph carries 18 kinds: `CONTAINS`, `IMPORTS`, `EXPORTS`, `CALLS`,
`MAY_CALL`, `INHERITS`, `IMPLEMENTS`, `OVERRIDES`, `ROUTES_TO`, `TESTS`,
`CONSUMES_FIXTURE`, `DOCUMENTS`, `READS`, `WRITES`, `QUERIES`, `CONFIGURES`,
`REFERENCES`, `DEPENDS_ON`.

`TESTS` is **derivation-tiered**: a test that imports and calls the target
directly is `high_confidence_heuristic`; a resolved call to a method of an
imported class is `static_resolved`; a test reaching it only through a pytest
fixture or a helper call is `low_confidence_heuristic` — still citable, but it
*explains* a coverage gap rather than closing it.

### Change preflight — the core workflow

```powershell
uv run codeatlas impact <repository_id>                          # working tree vs HEAD
uv run codeatlas impact <repository_id> --base main
uv run codeatlas impact <repository_id> --commits HEAD~1..HEAD
uv run codeatlas impact <repository_id> --since main             # from the real merge base
uv run codeatlas impact <repository_id> --format sarif
uv run codeatlas impact <repository_id> --fail-on high           # exit 7 at/above a severity
```

It maps diff hunks to syntax ranges, detects changed symbols and public-contract
deltas, computes direct and bounded transitive impact from the relation graph,
adds related tests, documents, configuration and schemas, evaluates architecture
rules, and orders findings by risk. Base-side evidence is labelled historical.

`--since main` is deliberately **not** `--base main`: a two-dot diff against a
moved trunk reports the trunk's own commits as your changes, inverted, so
`--since` resolves a real merge base.

**Formats:** `text` (default, shaped for a terminal), `json` (canonical),
`markdown`, `pr` (PR-ready), `sarif` (2.1.0, for scanners).

### Conversations and the web app

A persistent, ChatGPT-shaped interface backed by repository evidence — sidebar
history, an evidence drawer, and a change-preflight screen.

- **Backend owns the history.** Conversations and messages survive both browser
  and backend restarts; the frontend caches, it does not own truth.
- **Accept-then-stream** (ADR-0008): submitting a message returns `202` with
  IDs immediately, the answer runs on a worker, and the client follows typed
  Server-Sent Events. A long answer never holds a request open, cancelling
  reaches a run that is genuinely executing, and a reload recovers the persisted
  answer with its citations.
- **Inline `[n]` citations** are buttons; the evidence panel mounts only when you
  choose one, showing path, symbol, line range, derivation, confidence, and
  snapshot.
- Markdown is sanitized — repository text can never inject HTML, scripts, or
  application instructions.
- Light and dark themes, WCAG 2.2 AA as a release requirement, and a responsive
  layout where the evidence rail becomes an overlay then a sheet.

### Reports and interchange

JSON is canonical; Markdown is for humans; **SARIF 2.1.0** is for compatible
scanners and is deliberately not the internal domain model.

---

## How it works

### The five layers

```text
local repo
  → validated snapshot            (registration, scan, parse, extract, chunk, index, validate)
  → retrieval channels            (exact · lexical · graph · git · optional semantic)
  → verified evidence             (every object re-checked against the snapshot)
  → answer, report, or finding    (structured first; prose only as a derived view)
  → four surfaces                 (CLI · REST · MCP · web — one implementation)
```

### Snapshot lifecycle

```text
discovered → scanning → parsing → indexing → validating → active
                           ↓          ↓
                        failed     failed
active → superseded
```

Vector coverage is tracked separately and can **never** block deterministic
activation. Component versions are stamped into each snapshot — parser bundle
`1.4.0`, chunker `1.1.0`, resolver `1.4.0` — and a change to any of them makes
existing snapshots stale and forces a reindex.

### The answer pipeline

Validate input and limits → resolve the active or requested snapshot → classify
intent with deterministic rules → plan the minimum retrieval channels → resolve
exact paths and symbols first → lexical and bounded graph retrieval → Git-aware
retrieval for change questions → optional semantic candidates → fuse without
erasing derivation → pack evidence under item and token limits → **validate every
evidence object against the snapshot** → build the structured answer → optionally
generate prose over that evidence only → re-validate claims and citations →
persist run, answer, evidence, warnings, telemetry → stream typed events.

Every request is bounded: query length, per-channel result counts, graph depth
and visited nodes, evidence items and bytes, parser/Git/storage/provider/
end-to-end timeouts, cooperative cancellation, and a correlation ID.

### Change preflight pipeline

```text
git diff (working tree or commit range)
  → map diff hunks to syntax ranges
  → changed symbols + public-contract deltas
  → direct impact, then bounded transitive impact via the relation graph
  → related tests, documents, configuration, schemas
  → architecture-rule evaluation
  → risk ordering
  → JSON / Markdown / PR / SARIF / text
```

### Architecture

A **modular monolith**. SQLite is the system of record — one file, no daemon,
real transactions. No microservices, no message broker, no second database.

```text
src/codeatlas/
├── contracts.py      # the versioned response envelope
├── domain/           # pure types and invariants — imports nothing outward
├── application/      # use cases; the ONLY thing adapters may call
├── repositories/     # registration, scanning, ignore rules, Git state
├── parsing/          # Tree-sitter + ast
├── extraction/       # symbols and relations (two stages: reference → resolution)
├── chunking/         # logical chunk identity and versions
├── indexing/         # snapshot lifecycle, jobs, watcher, reconcile
├── retrieval/        # exact, lexical (FTS5), graph, git, semantic
├── analysis/         # change assurance, impact, risk ordering
├── generation/       # optional narrative over verified evidence
├── semantic/         # embeddings, vector store, migrations
├── conversations/    # threads, messages, runs, feedback
├── storage/sqlite/   # numbered, explicit, forward-only migrations
├── delivery/         # report rendering: JSON, Markdown, SARIF
├── api/ · cli/ · mcp/  # adapters — thin
├── settings/         # .env, Windows Credential Manager
└── evaluation/
```

Three rules of thumb:

- **Adapters are thin.** They translate transport to an application-service call
  and back. Repository logic never lives in an adapter, and never in two of them.
- **`domain/` imports nothing outward.** No FastAPI, no Typer, no SQLite, no
  provider SDK. If a domain module needs one, the design is wrong.
- **Types are generated.** `scripts/generate_web_types.ps1` regenerates the
  frontend API types from the OpenAPI export. Never hand-edit them.

### Stack

**Backend** — Python 3.12, FastAPI, Pydantic, SQLite (WAL), Tree-sitter, Python
`ast`, Typer, `mcp`, watchdog, uvicorn, PyInstaller (dev only).
**Frontend** — React 18 + TypeScript, Vite, TanStack Query, Zustand, Tailwind
CSS v4 over design tokens, Radix primitives, react-markdown + rehype-sanitize,
react-router-dom, Vitest + Testing Library + vitest-axe, Playwright.
**Optional** — LanceDB, sentence-transformers, OpenAI, Ollama. All lazily
imported, so an install without the extras is never an import error.

> **uvicorn runs with `access_log=False` deliberately.** One access-log line per
> request is written on the event-loop thread, so a server whose stdout pipe
> nobody drains blocks forever and stops answering. This was diagnosed the hard
> way in Phase 6 — see `docs/evaluation/phase-6-baseline-environment.md`.

---

## The four surfaces

CLI, REST, MCP, and the web app all call the **same application services** and
return the same evidence model. A difference between them is a defect.

### CLI

```powershell
uv run codeatlas <command> [args] [--json] [--db <path>]
```

| Command | What it does |
| --- | --- |
| `repo add <path>` | Register a local repository |
| `repo list` | List registered repositories |
| `repo watch <id>` | Show or change whether a repository is watched (`--enable` / `--disable`) |
| `repo remove <id>` | Remove a repository. Source files are never touched |
| `index <id>` | Build and activate a snapshot |
| `status <id>` | Index freshness and coverage |
| `rollback <id>` | Restore the previous snapshot as active |
| `symbol <id> <name>` | Resolve an exact symbol to verified file-and-line evidence |
| `search <id> <query>` | Search the active snapshot — `--kind text\|files\|symbols` (default `text`), `--limit` |
| `callers <id> <symbol>` | Symbols that call this one (`--depth`) |
| `callees <id> <symbol>` | Symbols this one calls (`--depth`) |
| `deps <id> <symbol>` | What it depends on, or what depends on it (`--direction`) |
| `exports <id> <module>` | What a module exports |
| `tests <id> <symbol>` | Tests that exercise this symbol |
| `trace <id> <entry>` | Bounded relation paths from an entry point |
| `evidence <id> <evidence_id>` | Re-read and re-verify one cited region |
| `files <id>` | Files in the active snapshot |
| `diagnostics <id>` | Indexing diagnostics |
| `impact <id>` | **Change preflight** (see above) |
| `analysis <analysis_id>` | Print a stored analysis — the same rows every adapter reads |
| `serve` | Run the local API, optionally with the web app |
| `doctor` | Health of the installation and its repositories |
| `backup <path>` / `restore <path>` | Copy or replace the database, verified |
| `upgrade` | Bring the database up to this build's schema |
| `purge` | Permanently remove long-deleted conversations |
| `settings <id>` | Show or change one repository's provider settings |
| `models` | Embedding providers and whether each can run here |

Every command that opens a database prints `Using database: <path>` to **stderr**
— never stdout, because `--json` promises a machine-readable stdout and a
diagnostic line there would break every scripted caller.

**Exit codes** distinguish outcomes so scripts can act on them:

| Code | Meaning |
| ---: | --- |
| `0` | Success |
| `2` | Invalid input |
| `3` | Repository or resource unavailable |
| `4` | Ran successfully and found nothing to report — *not* a failure |
| `5` | Policy failure |
| `6` | Internal failure |
| `7` | A finding met or exceeded `--fail-on` |

### REST API — `/v1`, loopback only

**Repositories** — `POST|GET /v1/repositories` · `GET|DELETE
/v1/repositories/{id}` · `POST /v1/repositories/{id}/index` · `POST
/v1/repositories/{id}/rollback` · `GET /v1/repositories/{id}/status` ·
`/files` · `/diagnostics` · `/snapshots/active` · `/semantic-status` ·
`GET|PUT /v1/repositories/{id}/watch`

**Conversations** — `POST|GET /v1/conversations` · `GET|PATCH|DELETE
/v1/conversations/{id}` · `GET|POST /v1/conversations/{id}/messages` ·
`GET /v1/conversations/{id}/stream` · `POST
/v1/conversations/messages/{message_id}/retry` · `.../feedback` ·
`POST /v1/message-runs/{run_id}/cancel`

**Intelligence** — `POST /v1/query` · `GET /v1/evidence/{evidence_id}` ·
`GET /v1/files/{file_id}` · `GET /v1/symbols/{symbol_id}` ·
`GET /v1/symbols/{symbol}/relations` · `GET /v1/search/text|files|symbols`

**Change analysis** — `POST /v1/change-analysis/working-tree` ·
`POST /v1/change-analysis/commits` · `GET /v1/change-analysis/{id}` ·
`GET /v1/change-analysis/{id}/report`

**Settings, providers, credentials** — `GET|PATCH /v1/settings` ·
`GET /v1/models` · `POST /v1/models/test` ·
`POST /v1/models/embedding/validate` · `POST|GET
/v1/models/embedding-migrations[/{id}]` · `.../activate` ·
`GET /v1/credentials` · `PUT|DELETE /v1/credentials/openai`

One error envelope everywhere — stack traces and filesystem paths never reach
the client:

```json
{ "error": { "code": "SNAPSHOT_NOT_READY", "message": "...",
             "request_id": "...", "retryable": true, "details": {} } }
```

### MCP — for coding agents

Tool schema version `1.0`. Registered tools: `register_repository`,
`list_repositories`, `get_repository`, `get_status`, `get_diagnostics`,
`resolve_symbol`, `resolve_file`, `search_files`, `search_symbols`,
`search_text`, `get_evidence`, `get_callers`, `get_callees`,
`get_dependencies`, `get_exports`, `get_related_tests`, `get_related_documents`,
`analyze_working_tree`, `analyze_commit_range`, `get_change_analysis`,
`get_change_report`.

Inputs and outputs are bounded and versioned. A tool returns warnings and
unsupported states rather than silently omitting them.

### Web app

`uv run codeatlas serve --web --open` serves the built app and `/v1` from the
**same loopback origin**, which is what lets the API stay loopback-bound with no
CORS relaxation. `--host` accepts loopback addresses only; anything else exits
with `INVALID_REQUEST`.

---

## Configuration and optional providers

Configuration lives in `.env` **in the project folder**, copied from
`.env.example`. It is deliberately not read from your current directory: *a
repository you index must never be able to configure the tool indexing it.*

Every optional service is **off by default and granted per repository**. A key in
`.env` enables nothing on its own — consent is a repository setting.

| Service | Purpose | Transmits? | Enabled by |
| --- | --- | --- | --- |
| Ollama (`llama3.2:3b`, `127.0.0.1:11434`) | written answers | No | Settings, per repository |
| OpenAI embeddings (`text-embedding-3-small`) | semantic recall | **Yes** | Settings + key |
| OpenAI answers (`gpt-4o-mini`) | written answers | **Yes** | Settings + key + a token budget |
| sentence-transformers | local embeddings | No | `uv sync --extra semantic-local` |
| LanceDB | vector storage | No | either semantic extra |
| Git CLI | diff and history | No | required; argument-array subprocess, never a shell |

A transmitting provider **cannot** be enabled without a spending bound.
Disablement, failure, timeout, or an exhausted budget degrades to the
deterministic result — it never fails the request.

**Embedding models are measured, not declared.** A repository using the local
provider picks any sentence-transformers model in Settings; the candidate is
loaded once and its *true* vector width reported before the choice can be saved
(ADR-0014), because the namespace is labelled with that number and a wrong label
never raises — it just returns worse results for as long as the index lives.

**The OpenAI key** can be entered in Settings and is stored in the **Windows
Credential Manager**, not in `.env` and not in SQLite — the database is copied by
backup and attached to bug reports (ADR-0015). Precedence is store → `.env`. No
response returns the key or any part of it (no last-4 mask: a suffix is still key
material), and the resolved key is never written back into `os.environ`, because
Git runs as a subprocess and would inherit it.

**CodeAtlas never downloads a model for you.** Settings names the model it
expects and shows the `ollama pull …` command for you to run in a terminal. There
is no pull endpoint, deliberately.

---

## Operating it

### Keeping the index fresh

```powershell
uv run codeatlas repo watch <id> --enable
```

**A filesystem event is a trigger, never an authority.** An event says *look
here*; a reconciling scan and the content hashes decide what actually changed.
Events are debounced so half-written saves are not indexed, a periodic scan plus
an immediate startup catch-up covers what the event stream silently drops, and
the watcher is disableable per repository.

### When something breaks

```powershell
uv run codeatlas doctor
```

A killed process runs no Python at all — no `except`, no cleanup. `doctor`
reports what was interrupted, what is blocking a reindex, and which repositories
were **never indexed**, telling those apart because the remedies differ. Recovery
leaves a run alone while the process that owns it is still alive, so it never
interrupts an index the watcher is mid-way through.

### Backup, restore, upgrade

```powershell
uv run codeatlas backup C:\backups\codeatlas.sqlite
uv run codeatlas restore C:\backups\codeatlas.sqlite
uv run codeatlas upgrade
```

Backup uses SQLite's online backup API and verifies the copy before keeping it.
Restore validates integrity **and** schema version before replacing anything,
and keeps the database it replaced. Migrations write a verified checkpoint first.
A build pointed at a *newer* database refuses outright rather than answering from
a schema it has never seen. Removing a repository never touches source files and
refuses to take conversations with it unless asked.

### Packaged build

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1
dist\codeatlas-win64\codeatlas.exe serve --web --open
```

Unzip and run — no install, no elevation. **Packaging changes no runtime
contract**: a packaged build answers exactly what a source checkout answers, and
a difference is a defect.

> ⚠️ **Rebuild the package whenever the web app changes.** There are two built
> bundles and the server picks by launch mode — a source checkout serves
> `apps/web/dist`, the packaged executable serves its own copy. A stale package
> serves an old UI while every source-run probe "confirms" the fix. This cost
> three misdirected workarounds in 2026-08; if a UI looks older than the code,
> **ask which command started the server before touching cache headers.**

### Ephemeral sessions

```powershell
uv run codeatlas serve --web --ephemeral
```

Starts from empty storage and discards it when the server stops (ADR-0013) — for
working *on* CodeAtlas, where a session inheriting the last run's repositories
makes new behaviour hard to tell from residue. It never opens the real database,
an explicit `--db` outranks it, and `CODEATLAS_EPHEMERAL_REPOSITORIES` names
repositories to register at startup.

**Scope note:** `CODEATLAS_EPHEMERAL` governs `serve` only. CLI commands always
open the real database — a CLI command exits immediately, so a session database
would make every invocation an island (ADR-0040). Both surfaces now announce
their database path, so the difference is visible rather than surprising.

---

## Security and privacy

Every control below is enforced, not aspirational — see
`docs/security/threat-model.md`.

- **Nothing leaves the machine** without a per-repository opt-in for a specific
  provider.
- **Repository code is never executed** during indexing — no imports, builds,
  tests, package scripts, hooks, binaries, or generated commands.
- **All repository text is untrusted input**, including filenames and Git
  metadata. Prompt injection in a document is data, not an instruction.
- **Paths are canonicalized** and confirmed inside the approved root; symlinks
  and Windows junctions get resolved-target containment checks.
- **Git runs through an argument-array subprocess adapter**, never a shell.
- **FTS queries are built by a validated builder** — user text is data, never
  syntax.
- **Rendered Markdown and links are sanitized** in the web app.
- **The API binds to loopback**, and widening it would need authentication, a
  CSRF/CORS review, a revised threat model, and explicit approval.
- **No source, prompt, evidence, model output, secret, or absolute local path is
  logged by default.**
- Secrets never appear in a GET response, a log, browser storage, an export, or a
  diagnostic bundle.

---

## Measured results and known limits

Numbers here name their method. The full target table is `AGENTS.md` §19.3;
caveats live in `docs/evaluation/*-baseline-environment.md`.

| Measure | Result |
| --- | --- |
| Valid file-and-line evidence | 100% |
| Active-snapshot leakage | 0 |
| Exact symbol resolution | **1.0000** (corpus: 65 query cases, 28 change cases, 7 fixtures) |
| Changed-symbol recall · direct-impact recall | 1.0000 · 1.0000 |
| Unsupported factual claim rate | 0.0000 |
| Containing-evidence Recall@10 | **1.0000** |
| Relation-path recall | **1.0000**, gated at 1.0 absolutely (ADR-0058) |
| Packaged refresh p95 · preflight p95 | 0.975 s · 2.298 s (semantic-local, on the artifact) |

**Performance, corrected 2026-08-18 (ADR-0064).** Preflight on a real 706-file
repository was **635 s**; it is now **21.6 s median**, and a cold index went
~343 s → 32.6 s. Three earlier records blamed parsing, because a timer named
`parse_base` actually wraps list, read, parse *and* resolve. Timed separately:
parse 8.14 s (2.5%), resolve 310.24 s (97.0%). `resolution.py` claimed
`O(references), not O(references × symbols)` in its own docstring while three
call sites scanned every symbol per reference. Indexing them gave **313.97 s →
3.55 s, 88×**, verified identical across all 168,605 relations.

### Known limits — stated, not hidden

- **Language coverage** is Python, TypeScript, JavaScript, Markdown, and common
  config/schema formats. A repository in any other language — Go, Java, C#,
  Rust, Ruby, PHP, C/C++, Kotlin, Swift, Scala — yields **zero symbols and zero
  relations**: file listing, full-text search, and a Git diff, but no symbol
  lookup, no callers, and no impact analysis. A new language needs an approved
  ADR under §25.

  **Java, Go, Rust and Scala shipped 2026-08-19 (ADR-0065)** through one shared
  query-backed parser: symbols, qualified names, calls, references, and
  changed-symbol detection, with **no test edges and no route detection** — so
  preflight on them stays thinner than on Python.

  Two limits are declared rather than hidden. **A Go import resolves as
  `external`**: its path carries the module prefix from `go.mod`, which a pure
  parse never reads. Rust's `crate` is a *language keyword*, so Rust imports do
  resolve — the contrast is the whole diagnosis. And **Scala captures only calls
  to a bare identifier**, not `obj.method(x)`, because its shipped `tags.scm`
  lacks the member-call pattern the other three have — and deliberately **no test edges and no route detection**, so
  preflight on Java is thinner than on Python. Query captures carry no receiver
  context, so Java also resolves calls less completely than Python does; that
  is a declared limit of the mechanism, not a defect. A spike on 2026-08-19
  measured Tree-sitter's shipped `tags.scm` files: all eleven requested grammars
  install, but only **nine ship a `tags.scm`** (C# and Kotlin ship none), and
  **none of the nine captures an import** — which matters because resolution is
  built on the import graph. Java, Go, Rust and Scala were the four that
  measured well on both definitions and references. If accepted, it would give
  those four symbols, `IMPORTS`, `CALLS`, `INHERITS`, `IMPLEMENTS`, and
  changed-symbol detection — deliberately **not** test edges or route
  detection, so preflight on them would stay thinner than on Python. See
  ADR-0065 and
  `docs/superpowers/specs/2026-08-19-query-backed-language-support-design.md`.
- **The packaged executable is unsigned**, so SmartScreen warns on first run.
  This needs a purchased certificate — a purchasing decision, not an engineering
  task.
- **Seven Playwright tests are skipped on Chromium** across five spec files; the
  renderer dies on a client-side navigation. Firefox runs all seven, so coverage
  is not lost. A separate, *failing* Chromium settings test was found
  2026-08-18, reproduces on `main`, and is under investigation.
- **The semantic-local packaged tree is 1.05 GB** (torch), accepted at the
  Phase 7 activation gate.
- **Changed-symbol precision is 0.9375 against a ≥0.95 target** — structural, not
  a defect: three corpus cases split one physical diff into three single-symbol
  cases that count each other's symbols against them. The other 21 score 1.0.
  The corpus is never edited to move a number (ADR-0003).
- **Phase 7's primary evidence Recall@10 missed its ≥0.90 target**, measured at
  0.6667 at the gate. On the semantic corpus today it reads **0.80** under the
  strict line-range metric and **1.0000** under the containment-based metric
  ADR-0027 introduced — which was a *corrected definition and no engine change*,
  so it must never be cited as uplift. If you quote the semantic uplift, read
  `docs/evaluation/phase-7-baseline-environment.md` first: the lexical stopword
  defect fixed alongside it was worth **+0.53** recall, the entire semantic layer
  on top **+0.07**.
- **Reranking and generated explanations were built, measured, and declined** —
  neither improved a metric over the admitted semantic baseline.
- No GitHub/GitLab or CI integration, no multi-user tenancy, no enterprise
  control plane.

The authoritative list of everything still open is the **Deferred Register** in
`docs/plans/PLAN.md`, where each item is closed or deferred with a stated reason
and a named trigger that reopens it.

---

## Developing CodeAtlas

### Repository layout

```text
CodeAtlas_V2/
├── AGENTS.md · CLAUDE.md          # the coding-agent contract (one contract, two entry names)
├── CODEATLAS_INDUSTRY_BLUEPRINT_2026.md   # product rationale
├── apps/{api,cli,web}/            # entry points; web/e2e holds the Playwright specs
├── src/codeatlas/                 # the product (see Architecture above)
├── tests/                         # unit · integration · contract · end_to_end
│                                  # security · retrieval · evaluation · fixtures
├── docs/{adr,evaluation,operations,plans,security}/
├── documentation/                 # PRD, architecture, rules, phases, design, memory
├── packaging/ · scripts/
```

### The dev loop

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_dev.ps1
```

Starts uvicorn on 8000 and Vite in front of it with `/v1` proxied, so the browser
still sees one origin. `-ApiOnly` runs the backend alone; `-ApiPort` moves it.
The script stops the API when you exit Vite, so no stray process holds the port.

Changed a REST endpoint? Regenerate the frontend types — never hand-edit them:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/generate_web_types.ps1
```

### Quality gates

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync -SkipE2E
```

Validates the tracked contract schema, the Python suite, Ruff, strict MyPy, the
evaluation corpus, the tracked Phase 0/3/4 baselines and ADR-0016 invariants, and
the web app's lint, types, component tests, and build. Unlike earlier phase
scripts it runs the Playwright suites **inside** the gate; `-SkipE2E` opts out
for a fast inner loop. `scripts/check_phase0.ps1` … `check_phase7.ps1` each still
prove their own phase.

Run gates one at a time. Progress dots that stop with no failure summary mean a
**terminated process**, not a broken test — read the whole log before believing a
gate result, and re-run in isolation before calling anything a regression.

### House rules for contributors and agents

`AGENTS.md` is the release-blocking contract; `documentation/rules.md` is the
blunt version. The ones that bite most often:

- **Test-first, and mutation-check every fix.** Behaviour that already works
  produces tests that pass whether or not they assert anything useful. Break the
  invariant and watch the test fail before believing it.
- **Never edit the tree you are measuring.** A preflight over a live working tree
  is not atomic; a file caught mid-write reads as empty and reports every symbol
  in it deleted.
- **The evaluation corpus is never edited to move a number** (ADR-0003). Adding
  coverage is legitimate; changing an expectation needs a recorded justification.
- **Declare any change** to `PARSER_BUNDLE_VERSION`, `CHUNKER_VERSION`, or
  `RESOLVER_VERSION` — it makes every snapshot stale and forces a reindex.
- **Append handoffs to `docs/plans/PLAN.md`; never rewrite them.** Rewriting the
  evidence a gate was approved on is not a refactor.
- **Do not claim a test passed unless you ran it here.** If a platform-specific
  check cannot run, say so precisely.
- Ask before adding a dependency, and never upgrade a major one as part of
  unrelated work.

### Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `INVALID_REQUEST: the web application has not been built` | `pnpm --dir apps/web build`, or use the packaged release |
| `--host must be a loopback address` | Loopback only, by design. Use `127.0.0.1` |
| Port already in use | `--port` on `serve`, `-ApiPort` on `run_dev.ps1` |
| Script will not run | Use the `-ExecutionPolicy Bypass -File` form |
| A repository will not reindex | `codeatlas doctor` names the blocking run and its pid |
| The UI looks older than the code | You are almost certainly running the packaged build. Rebuild with `scripts/build_package.ps1` |
| An embedding option is greyed out | Its optional extra is not installed — `uv sync --extra semantic-local` |

---

## Documentation map

**Start here**

| Document | For |
| --- | --- |
| `AGENTS.md` / `CLAUDE.md` | The release-blocking contract. Overrides everything else |
| `docs/plans/PLAN.md` | Live task status, the Deferred Register, and the append-only handoff log |
| `documentation/codeatlas-v2-working-guide.md` | One-document orientation: what it is, scenarios, differentiation |
| `CODEATLAS_INDUSTRY_BLUEPRINT_2026.md` | Product rationale and deeper technical detail |

**Product and design**

`documentation/PRD.md` (scope and non-goals) · `documentation/architecture.md`
(stack, structure, data model, flows) · `documentation/rules.md` (constraints) ·
`documentation/phases.md` (build order and what shipped) ·
`documentation/design.md` (the design system) · `documentation/memory.md`
(prior context, decisions, known issues)

**Operations**

`docs/operations/` — `change-analysis.md` · `chunking-and-search.md` ·
`relations-and-graph.md` · `continuous-freshness.md` · `crash-recovery.md` ·
`backup-and-restore.md` · `upgrade-and-migration.md` ·
`packaging-and-install.md` · `release-validation.md` · `web-application.md` ·
`end-to-end-tests.md` · `semantic-search.md` · `answer-generation.md` ·
`ephemeral-sessions.md` · `development-windows.md`

**Decisions and measurement**

`docs/adr/README.md` — 64 accepted records and their rationale ·
`docs/evaluation/` — baselines and the environment documents that say how to read
them · `docs/security/threat-model.md`

> Where a summary and an authority disagree, **the authority wins and the summary
> is the bug.** `AGENTS.md` and `docs/plans/PLAN.md` are the authorities.
