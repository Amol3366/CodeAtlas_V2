# Architecture — CodeAtlas

Status: current as of 2026-08-07
Normative source: `AGENTS.md` Sections 6–17. This file is the navigable map;
that file is the contract.

## Tech Stack

### Backend

| Choice | Version | Why |
| --- | --- | --- |
| Python | 3.12 (`>=3.12,<3.13`) | Pinned; Tree-sitter and `ast` behavior are version-sensitive |
| FastAPI | `>=0.140,<1` | Local HTTP plus SSE streaming without a second server |
| Pydantic | `>=2.12,<3` | Validation at the boundary; also drives settings |
| SQLite (WAL) | stdlib | Single-user local product — one file, no daemon, real transactions |
| Tree-sitter | `>=0.25,<0.27` | One parser family across Python/TS/JS/Java; error-tolerant on broken files |
| `tree-sitter-java` / `-go` / `-rust` / `-scala` | pinned | Grammars for ADR-0065. Only Java is wired up; the other three are approved and not yet built |
| Python `ast` | stdlib | Enriches Tree-sitter output where Python semantics matter |
| Typer | `>=0.27,<1` | Typed CLI over the same application services |
| `mcp` | `>=1.2,<2` | Agent access surface |
| watchdog | `>=6.0` | Filesystem events — debounced, and never treated as truth on their own |
| uvicorn | `>=0.51,<1` | ASGI host. Runs with `access_log=False`; see the note below |
| PyInstaller | dev only | Packaged Windows build; the artifact contains no packer |

Optional extras, never required for deterministic operation:
`semantic-local` (lancedb + sentence-transformers) and `semantic-openai`
(lancedb + openai for embeddings or written answers). Ollama uses its local HTTP
API and no Python provider extra. Provider packages are imported lazily, so
their absence is not an import error.

> **uvicorn access logging is off deliberately.** One access-log line per
> request is written on the event-loop thread; a server whose stdout pipe
> nobody drains blocks forever and stops answering. This was diagnosed in
> Phase 6 and is recorded in `docs/evaluation/phase-6-baseline-environment.md`.

### Frontend

| Choice | Version | Why |
| --- | --- | --- |
| React + TypeScript | 18.3 / 5.7 | Standard, well-supported |
| Vite | ^6.0 | Build and dev server |
| TanStack Query | ^5.66 | Server state; the backend owns truth, the client caches |
| Zustand | ^5.0 | Small local UI state only |
| Tailwind CSS | ^4.0 | Utility CSS over the tokens in `styles/tokens.css` |
| Radix UI | dialog / dropdown / tooltip | Accessible primitives, not a full component library |
| react-markdown + rehype-sanitize | ^9 / ^6 | Repository text is untrusted; sanitizing is mandatory |
| react-router-dom | ^6.28 | URL identifies the active conversation |
| openapi-typescript | ^7.13 | API types are generated, never hand-maintained |
| Vitest + Testing Library + vitest-axe | — | Component and accessibility tests |
| Playwright | ^1.62 | Critical end-to-end workflows |

Streaming is Server-Sent Events, not WebSockets: the flow is one-way.

Packaged/source web serving uses the FastAPI process too. `serve --web` serves
the built `apps/web/dist` application and the `/v1` API from the same loopback
server. The application shell is intentionally non-cacheable so a new packaged
bundle is not hidden behind a stale `index.html`. The React shell also has a
small build-freshness check and the Settings sidebar link performs document
navigation, both aimed at preventing an old Settings bundle from staying alive
after a new build.

## Folder Structure

```text
CodeAtlas_V2/
├── AGENTS.md                              # authoritative agent contract (maintained body)
├── CLAUDE.md                              # Claude entry point -> AGENTS.md
├── CODEATLAS_INDUSTRY_BLUEPRINT_2026.md   # product rationale
├── README.md
├── pyproject.toml / uv.lock
├── .env.example                           # read from the project folder, never the indexed repo
├── apps/
│   ├── api/                               # FastAPI entry point
│   ├── cli/                               # Typer entry point
│   └── web/
│       ├── e2e/                           # Playwright specs
│       └── src/
│           ├── app/                        # shell, providers, theme
│           ├── components/                 # reusable UI only, no data fetching
│           ├── features/
│           │   ├── change-analysis/
│           │   ├── conversations/
│           │   ├── evidence/
│           │   ├── repositories/
│           │   └── settings/
│           ├── lib/                        # api client, generated types, utils
│           ├── routes/                     # one file per route
│           ├── styles/tokens.css           # the design system, see design.md
│           └── test/
├── src/codeatlas/
│   ├── contracts.py                        # the versioned response envelope
│   ├── domain/                             # pure types and invariants — imports nothing outward
│   ├── application/                        # use cases; the ONLY thing adapters may call
│   ├── repositories/                       # registration, scanning, ignore rules, Git state
│   ├── parsing/                            # Tree-sitter + ast
│   │   └── query_backed/                   # ADR-0065: one engine + per-language adapters
│   │       ├── engine.py                   #   runs tags.scm, builds SymbolRecords
│   │       ├── profile.py                  #   LanguageProfile / LanguageAdapter
│   │       ├── queries/                    #   imports.scm authored here
│   │       └── languages/                  #   java.py (go/rust/scala pending)
│   ├── extraction/                         # symbols and relations
│   ├── chunking/                           # logical chunk identity and versions
│   ├── indexing/                           # snapshot lifecycle, jobs, watcher, reconcile
│   ├── retrieval/                          # exact, lexical (FTS5), graph, git, semantic
│   ├── analysis/                           # change assurance, impact, risk ordering
│   ├── generation/                         # optional narrative over verified evidence
│   ├── semantic/                           # embeddings, vector store, migrations
│   ├── conversations/                      # threads, messages, runs, feedback
│   ├── storage/sqlite/migrations/          # numbered, explicit, forward-only
│   ├── delivery/                           # report rendering: JSON, Markdown, SARIF
│   ├── api/ · cli/ · mcp/                  # adapters — thin
│   ├── settings/                            # .env, credential store (ADR-0015)
│   └── evaluation/
├── tests/
│   ├── unit/ integration/ contract/ end_to_end/
│   ├── security/ retrieval/ evaluation/ fixtures/
├── docs/
│   ├── adr/                                # 0000-template + ADR-0001..0015
│   ├── api/ · evaluation/ · operations/ · security/
│   └── plans/PLAN.md                       # LIVE task status — the coordination file
├── documentation/                          # this folder: PRD, architecture, rules, phases, design, memory
├── packaging/
└── scripts/                                # check_phaseN.ps1, baselines, perf, setup, packaging
```

### Rules of thumb

- **Adapters are thin.** `api/`, `cli/`, `mcp/`, and `apps/web` translate
  transport to an application service call and back. Repository logic never
  lives in an adapter, and never in two of them.
- **`domain/` imports nothing outward.** No FastAPI, no Typer, no SQLite, no
  provider SDK. If a domain module needs one of those, the design is wrong.
- **Components receive props.** Data fetching lives in `features/*/` hooks over
  TanStack Query, not in `components/`.
- **Types are generated.** `scripts/generate_web_types.ps1` regenerates the
  frontend API types from the OpenAPI export. Do not hand-edit them.

## Data Model

SQLite is the system of record. Migrations `0001`–`0014` are numbered and
explicit; schema is never mutated at startup.

**Repository truth**

- `Repository` — id, canonical root, display path, Git metadata, settings,
  provider policy. `ProviderPolicy` carries the embedding and answer provider
  decisions separately — a repository may retrieve locally and answer remotely,
  or the reverse — plus token budgets, an optional per-repository `answer_model`
  (ADR-0012) and, for the local embedding provider, the repository's chosen
  `embedding_model` (ADR-0014). OpenAI embedding model identity stays machine-wide
  in `.env` (ADR-0011), because an unknown OpenAI id also needs a declared width.
- `Snapshot` — id, repository, Git HEAD, working-tree fingerprint, lifecycle
  state, parser/chunker/index versions. **Exactly one is active per repository.**
- `FileRecord` — stable logical id, snapshot membership, normalized relative
  path, content hash, language, classification, line map.
- `Symbol` — stable logical id + version id, kind, qualified name, signature,
  byte and line ranges, content hash.
- `Relation` — source, target, type, **derivation class**, confidence,
  supporting evidence, snapshot membership. `TESTS` is derivation-tiered: a
  test that imports and calls the target directly is
  `high_confidence_heuristic`; a resolved call to a method of an imported
  class is `static_resolved` (ADR-0021 — a method is never imported, so
  import-and-call is applied one level down, and the owner must be a class,
  never a module); a test reaching it only through a pytest
  fixture parameter or a helper call is `low_confidence_heuristic` and still
  citable in impact (ADR-0016). Only the first two close a `test_gaps`
  entry. `RelationKind.CONSUMES_FIXTURE` records a
  test requesting a fixture by parameter name — stored and citable, but
  excluded from impact-expansion walks; it names which fixture a test asked
  for, not what depends on what. `SymbolKind.FIXTURE` (declared since
  Phase 0) is now emitted for `@pytest.fixture`-decorated functions, and
  `conftest.py` classifies as test code so fixture-mediated edges have a
  source.
- `LogicalChunk` / `ChunkVersion` / `SnapshotChunkMembership` — chunk identity
  is stable across edits so unrelated chunks survive a one-symbol change.
- `Evidence` — file/symbol ids, line range, excerpt hash, derivation,
  validation state.
- `Finding` — code, severity, derivation, confidence, evidence ids, remediation.
- `ChangeAnalysis`, `IndexJob`.

**Conversation**

`Conversation` → `Message` → `MessageRun` → `MessageEvidence`, plus
`MessageFeedback`. A message stays bound to the snapshot that answered it.

**Semantic (optional)**

Embedding cache keyed by content hash + model + dimensions + normalization
version. Vectors live in LanceDB under base/delta namespaces, but **SQLite
snapshot membership is authoritative** — a physically retained stale vector is
excluded by membership, not by deletion.

### The derivation ladder

This enum is the spine of the whole product. Confidence is a *separate* field.

| Class | May support |
| --- | --- |
| `deterministic` | an authoritative finding |
| `static_resolved` | a finding, with stated language limitations |
| `high_confidence_heuristic` | a labeled heuristic finding |
| `low_confidence_heuristic` | advisory discovery only |
| `semantic_candidate` | a candidate only, never a fact |
| `model_generated` | narrative only |
| `unsupported` | nothing — must abstain |

## Core Flows

### Indexing

```text
discovered → scanning → parsing → indexing → validating → active
                            ↓          ↓
                         failed     failed
active → superseded
```

Work is built in staging. Before activation, entity membership, FTS rows,
relation endpoints, evidence ranges, and version metadata are validated.
Activation is a single atomic SQLite transaction — an interrupted index leaves
the previous active snapshot usable. Vector coverage is tracked separately and
can never block deterministic activation.

Incremental: an unchanged content hash reuses its chunk and embedding rows. Only
affected files, symbols, relations, chunks, FTS projections, and necessary
reverse relations recompute.

### A question, click to answer

```text
web/CLI/MCP
  → application service
  → validate input, resolve the active (or requested) snapshot
  → classify intent with deterministic rules
  → plan the minimum retrieval channels
  → exact path/symbol → lexical (FTS5) → bounded graph → git → [semantic]
  → fuse candidates WITHOUT erasing derivation
  → pack evidence under item and token limits
  → validate every evidence object against the snapshot
  → build the structured answer
  → [optionally generate prose over that evidence only]
  → re-validate claims and citations
  → persist run + answer + evidence + warnings
  → stream typed SSE events; the persisted answer is authoritative
```

Message submission is **accept-then-stream** (ADR-0008): the POST returns ids
immediately and the run streams. This is why `contract_version` is `1.1`.

Retrieval priority by intent, plus the per-request limits (query length, result
counts, graph depth, evidence bytes, timeouts, cancellation, correlation id),
are `AGENTS.md` Sections 10.2 and 10.3.

### Change preflight

```text
git diff (working tree or commit range)
  → map diff hunks to syntax ranges
  → changed symbols + public-contract deltas
  → direct impact, then bounded transitive impact via the relation graph
  → related tests, documents, configuration, schemas
  → architecture-rule evaluation
  → risk ordering
  → JSON / Markdown / SARIF
```

## API Surface

Versioned under `/v1`, bound to **loopback only**. Plural resources, opaque ids,
UTC timestamps, cursor pagination.

- Repositories: register, list, get, delete, index, status, files, diagnostics,
  active snapshot, semantic status
- Conversations: CRUD, messages, `GET .../stream`, retry, cancel, feedback
- Intelligence: `POST /v1/query`, `/v1/query/stream`, evidence, files, symbols,
  symbol relations, search (files / symbols / text)
- Change analysis: working-tree, commits, get, report
- Settings and providers: settings, models, model test, embedding-model
  validation, embedding migrations
- Credentials: `GET /v1/credentials`, `PUT`/`DELETE /v1/credentials/openai`
  (ADR-0015). Write-only; the GET reports `configured`, `source`, and
  `store_available` and has no field a value could occupy

One error envelope everywhere:

```json
{ "error": { "code": "SNAPSHOT_NOT_READY", "message": "...",
             "request_id": "...", "retryable": true, "details": {} } }
```

Stack traces and filesystem paths never reach the client. Provider secrets never
appear in a GET response, a log, browser storage, an export, or a diagnostic
bundle.

The exact schemas live in `src/codeatlas/contracts.py`, the versioned Pydantic
models, and the contract tests — not in this file.

## External Services

Every one of these is optional, off by default, and per repository.

| Service | Purpose | Transmits? | Enabled by |
| --- | --- | --- | --- |
| Ollama (`llama3.2:3b` default, `127.0.0.1:11434`) | written answers | No | Settings, per repository |
| OpenAI embeddings (`text-embedding-3-small`) | semantic recall; known dimensions auto-resolve from model id | **Yes** | Settings + `OPENAI_API_KEY` |
| OpenAI answers (`gpt-4o-mini`) | written answers | **Yes** | Settings + key + a token budget |
| sentence-transformers | local embeddings | No | `uv sync --extra semantic-local` |
| LanceDB | vector storage | No | either semantic extra |
| Git CLI | diff and history | No | required; argument-array subprocess, never a shell |

A transmitting provider cannot be enabled without a spending bound. Disablement,
failure, timeout, or an exhausted budget degrades to the deterministic result —
it never fails the request.

Configuration is read from `.env` **in the project folder**, not the working
directory: a repository you index must never be able to configure the tool
indexing it.

A repository using the local provider chooses its own embedding model in
Settings, and any sentence-transformers model is reachable. The candidate is
loaded once and its *measured* vector width reported through
`POST /v1/models/embedding/validate` before the choice can be saved (ADR-0014) —
the namespace is labelled with that width, and a wrong label never raises, it
just returns worse results for as long as the index lives.

OpenAI embedding model identity stays in `.env` (ADR-0011). Known OpenAI widths
are resolved from the selected model id where the mapping is built in; unknown
OpenAI-compatible ids still require explicit dimensions, because asking OpenAI
for the width costs a billable call per construction.

The OpenAI API key is entered in Settings and stored in the **Windows
Credential Manager**, machine-wide (ADR-0015) — not in SQLite, because the
database is copied by backup and attached to bug reports. Precedence is
credential store → `.env`, and `.env` stays supported for scripted runs.

`resolve_openai_api_key()` (`settings/credentials.py`) is the only place any
caller learns the key, and it **never writes the resolved value back into
`os.environ`**: CodeAtlas invokes Git as a subprocess, and a child inherits its
parent's environment. That rule is a test, not a comment.

**CodeAtlas never downloads a model for you.** Settings names the answer model
it expects and displays the `ollama pull …` command for you to run in a
terminal. There is no pull endpoint: `pull_ollama_model` was deleted on
2026-08-05 rather than left as unreachable code, and that decision was preserved
when ADR-0014 landed. `git show 63c57cd` has the implementation if it is ever
wanted.

## Where to Read Next

| Topic | File |
| --- | --- |
| Live task status | `docs/plans/PLAN.md` |
| Decisions and their rationale | `docs/adr/0001`–`0015` |
| Chunking, search, graph, change analysis | `docs/operations/*.md` |
| Measured numbers and their caveats | `docs/evaluation/*.md` |
