# CodeAtlas — Universal Coding-Agent Context

Version: 1.0  
Status: Authoritative implementation context  
Last updated: 2026-07-25  
Product blueprint: `CODEATLAS_INDUSTRY_BLUEPRINT_2026.md`

## 1. Purpose of This File

This file is the default operating contract for every coding agent working in the
CodeAtlas repository. Read it before planning or changing code.

Use the industry blueprint for product rationale and deeper technical detail.
Use this file for implementation decisions, constraints, delivery order, and
acceptance criteria. If the two documents appear to conflict:

1. preserve the product trust contract and security invariants in this file;
2. prefer the more specific requirement;
3. do not silently choose between materially different product behaviors;
4. record the decision in an ADR and ask for product approval when the choice
   changes scope, privacy, trust, compatibility, or deployment.

The objective is not to create a demo that resembles CodeAtlas. The objective is
to build a production-shaped, local-first repository intelligence and
change-assurance product through small, testable vertical slices.

## 2. Product Contract

CodeAtlas is a trusted repository-intelligence and change-assurance layer for
developers, reviewers, and coding agents.

It must answer five questions:

1. What changed?
2. What may be affected?
3. What evidence proves it?
4. How current is that evidence?
5. What does CodeAtlas not know?

The primary value workflow is change preflight:

> Before a developer or coding agent submits a change, CodeAtlas identifies what
> changed, what may break, which tests and documents are affected, which policies
> were violated, and the exact evidence supporting every finding.

CodeAtlas is not:

- a new IDE;
- a generic “chat with your codebase” wrapper;
- an autonomous code editor;
- a replacement for compilers, language servers, tests, SAST, SCA, or CI;
- a system that treats an LLM response as repository truth;
- a cloud-first product that requires source code to leave the workstation.

The chat interface is an access surface for verified repository intelligence. It
must not weaken the evidence, freshness, or abstention contracts.

## 3. Normative Language

- **MUST** and **MUST NOT** are release-blocking requirements.
- **SHOULD** is the default; deviations require a documented reason.
- **MAY** is optional and must not become an undeclared runtime dependency.
- **Deterministic** means reproducible from declared inputs and versioned logic.
  It does not mean static analysis perfectly predicts runtime behavior.

## 4. Non-Negotiable Invariants

Every implementation must preserve these invariants.

### 4.1 Evidence and truth

- Every material factual claim MUST reference one or more evidence IDs.
- Evidence MUST resolve against the selected repository snapshot.
- File paths, symbol identities, line ranges, and relation paths MUST be
  validated before a result leaves the application layer.
- Active results MUST NOT contain entities from another snapshot.
- Missing or invalid evidence MUST cause claim rejection, warning, or explicit
  abstention. Never invent a path, symbol, line, relation, test, or finding.
- Structured findings are authoritative. Natural-language explanations are
  derived views.

### 4.2 Freshness

- Every repository query MUST identify a repository and snapshot or Git state.
- Staging snapshots MUST NOT become active until required deterministic indexes
  are committed and validated.
- Interrupted indexing MUST leave the previous active snapshot usable.
- Exact, lexical, graph, and Git retrieval MUST remain available when semantic
  indexing is incomplete or unavailable.
- Physically retained stale vectors MUST be excluded by authoritative snapshot
  membership.

### 4.3 Deterministic before probabilistic

- Exact path/symbol lookup, parsing, Git diff mapping, graph traversal,
  architecture rules, test links, and evidence validation MUST NOT depend on an
  LLM.
- Embeddings, reranking, and generation are optional recall or presentation
  layers.
- A model score MUST NOT promote a probabilistic candidate to deterministic
  evidence.
- Provider disablement, failure, timeout, or exhausted budget MUST degrade to a
  useful deterministic result.

### 4.4 Local-first privacy and security

- No source or derived repository content may leave the machine unless the user
  explicitly enables a provider for that repository.
- Indexing MUST NOT execute repository code, imports, builds, tests, package
  scripts, hooks, binaries, or generated commands.
- Repository text, comments, documents, filenames, and metadata are untrusted
  input and never instructions to the application or model.
- Canonicalized paths MUST remain inside the approved repository root.
- Symlinks, junctions, traversal, malformed files, oversized files, deep trees,
  parser timeouts, binary files, and secret exposure require explicit handling.
- Source, prompts, retrieved evidence, and model output MUST NOT be logged by
  default.

### 4.5 Architecture

- Build a modular monolith. Do not introduce microservices, a message broker,
  Kubernetes, or distributed data infrastructure for the local product.
- CLI, REST, MCP, background jobs, and the web app MUST call the same
  application services. Do not duplicate repository logic in adapters.
- Domain logic MUST NOT import framework, HTTP, CLI, UI, or concrete provider
  code.
- Storage, parsers, vector stores, model providers, clocks, and IDs MUST be
  accessed through narrow interfaces where substitution benefits testing or
  future evolution.
- Changes MUST be incremental and scoped. Avoid unrelated refactors.

## 5. Initial Supported Product Profile

Unless an approved ADR changes the profile, target:

- single user;
- local Windows 11 workstation as the primary supported environment;
- local Git repositories;
- Python, TypeScript, and JavaScript source;
- Markdown and common configuration/schema formats;
- deterministic operation without a GPU, embedding model, or LLM;
- CLI, local REST API, MCP, JSON, Markdown, SARIF, and web UI;
- later optional Ollama or OpenAI providers;
- no GitHub/GitLab cloud integration in the MVP;
- no multi-user tenancy, RBAC, billing, or enterprise control plane in the MVP.

Cross-platform code is welcome, but Windows paths, process behavior, file
watching, packaging, and recovery are release requirements.

## 6. Approved Technical Direction

Prefer stable, well-supported versions and pin them in lockfiles. Do not upgrade
major dependencies as part of unrelated work.

### 6.1 Backend

- Python 3.12 or the repository-pinned compatible version
- FastAPI for local HTTP and streaming endpoints
- Pydantic for boundary validation and settings
- SQLite with WAL mode for metadata, FTS5, graph edges, snapshots, jobs, chat
  history, and user settings
- Alembic or an equivalent explicit migration mechanism
- Tree-sitter for general parsing
- Python `ast` enrichment for Python
- TypeScript/JavaScript language-specific enrichment where it demonstrably
  improves relation accuracy
- Git CLI through a non-shell, argument-array subprocess adapter
- OpenTelemetry-compatible tracing and metrics
- LanceDB only when optional vector retrieval is admitted
- `uv` and `pyproject.toml` for Python dependency and task management

SQLite is the MVP system of record. Do not add PostgreSQL merely because the
product may later become multi-user.

### 6.2 Frontend

- React with TypeScript
- Vite-based application unless the existing repository has already selected
  another approved React build system
- a maintained utility-CSS and accessible component approach
- TanStack Query or an equivalent server-state layer
- a small local UI-state store only where React state is insufficient
- generated or centrally defined API types; do not hand-maintain divergent
  request/response models
- Server-Sent Events for one-way streamed answers and progress; use WebSockets
  only after proving bidirectional real-time behavior is required
- Vitest and Testing Library for component tests
- Playwright for critical end-to-end workflows

Do not make a browser-only database the authoritative chat store. The backend
owns conversations and messages; the frontend may cache them.

### 6.3 Delivery adapters

- Typer or an equivalent typed CLI layer
- versioned `/v1` REST contracts
- MCP tools that adapt the application service contracts
- JSON as the canonical interchange representation
- Markdown for human-readable reports
- SARIF 2.1.0 for compatible scanning findings, not as the internal domain model

## 7. Target Repository Structure

Follow existing structure when the project already contains implementation.
For a greenfield repository, converge toward:

```text
codeatlas/
├── AGENTS.md
├── README.md
├── CODEATLAS_INDUSTRY_BLUEPRINT_2026.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── config/
│   ├── default.yaml
│   ├── languages.yaml
│   ├── architecture-rules.example.yaml
│   └── logging.yaml
├── migrations/
├── apps/
│   ├── api/
│   │   └── main.py
│   ├── cli/
│   │   └── main.py
│   └── web/
│       ├── package.json
│       ├── pnpm-lock.yaml
│       ├── vite.config.ts
│       └── src/
│           ├── app/
│           ├── components/
│           ├── features/
│           │   ├── conversations/
│           │   ├── repositories/
│           │   ├── evidence/
│           │   ├── change-analysis/
│           │   └── settings/
│           ├── lib/
│           ├── routes/
│           └── styles/
├── src/
│   └── codeatlas/
│       ├── domain/
│       ├── application/
│       ├── repositories/
│       ├── parsing/
│       ├── extraction/
│       ├── chunking/
│       ├── indexing/
│       ├── retrieval/
│       ├── analysis/
│       ├── verification/
│       ├── conversations/
│       ├── generation/
│       ├── storage/
│       │   ├── sqlite/
│       │   └── lancedb/
│       ├── delivery/
│       ├── api/
│       ├── mcp/
│       ├── cli/
│       ├── settings/
│       └── observability/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── end_to_end/
│   ├── security/
│   ├── retrieval/
│   ├── evaluation/
│   └── fixtures/
├── docs/
│   ├── adr/
│   ├── api/
│   └── operations/
└── scripts/
    ├── setup_windows.ps1
    ├── run_dev.ps1
    ├── run_evaluation.py
    └── check_storage_consistency.py
```

Keep files focused. A module should expose a clear purpose, public interface,
dependencies, and failure behavior without requiring consumers to understand
its internals.

## 8. Backend Domain Model

Use typed domain concepts. Do not pass loose dictionaries through core logic.
Identifiers are opaque strings or strongly typed value objects; never derive
authorization or identity from display names.

### 8.1 Repository truth

At minimum model:

- `Repository`: ID, canonical root, display path, Git metadata, settings,
  provider policy, created/updated timestamps.
- `Snapshot`: ID, repository ID, Git HEAD, working-tree fingerprint, lifecycle
  state, parser/chunker/index versions, created/activated timestamps.
- `FileRecord`: stable logical ID, snapshot membership, normalized relative
  path, display path, content hash, language, classification, size, line map.
- `Symbol`: stable logical ID, version ID, kind, qualified name, signature,
  file ID, byte and line ranges, visibility, content hash.
- `Relation`: source, target, relation type, derivation class, confidence,
  supporting evidence, snapshot membership.
- `LogicalChunk`, `ChunkVersion`, and `SnapshotChunkMembership`.
- `Evidence`: ID, repository/snapshot IDs, file/symbol IDs, line range, excerpt
  hash, derivation, validation state.
- `Finding`: code, severity, title, description, derivation, confidence,
  evidence IDs, remediation, limitations.
- `ChangeAnalysis`: source/target Git state, changed files/symbols, findings,
  warnings, timing, status.
- `IndexJob`: stage, status, attempts, progress, diagnostics, timestamps.

### 8.2 Conversation and chat history

Chat history is first-class persistent application data:

- `Conversation`: ID, repository ID, title, created/updated timestamps, last
  message timestamp, archived timestamp, optional pinned snapshot policy.
- `Message`: ID, conversation ID, role (`user`, `assistant`, `system_event`),
  status (`queued`, `retrieving`, `generating`, `complete`, `failed`,
  `cancelled`), raw user text or rendered assistant text, created/completed
  timestamps, sequence number, error code.
- `MessageRun`: ID, message ID, repository ID, snapshot ID, normalized query,
  intent, retrieval policy version, generation policy/model metadata, latency,
  token/cost data, warnings.
- `MessageEvidence`: message ID, evidence ID, citation ordinal, claim IDs,
  presentation metadata.
- `MessageFeedback`: message ID, rating, reason code, optional comment.

Required behavior:

- history survives browser restart and backend restart;
- conversation ordering uses backend timestamps and stable pagination;
- creating a user message and queued run is transactional;
- completed assistant text and its evidence links are committed atomically;
- failed or cancelled runs remain visible and retryable;
- retries create a new run and preserve prior audit data;
- deleting a conversation is explicit and recoverable if soft deletion is used;
- deleting a repository requires an explicit policy for its conversations;
- conversation titles may be deterministic initially; model-generated titles
  are optional and non-authoritative;
- a historical message remains tied to the snapshot used for its answer;
- reopening history must not silently relabel old evidence as current.

## 9. Snapshot and Indexing State Machine

Use explicit states. Avoid booleans such as `is_indexed` that cannot represent
partial or failed work.

Recommended snapshot states:

```text
discovered -> scanning -> parsing -> indexing -> validating -> active
                                      |              |
                                      v              v
                                    failed         failed

active -> superseded
```

Rules:

- Only one deterministic snapshot is active per repository.
- Build in staging records or a staging database boundary.
- Validate entity membership, FTS rows, relation endpoints, evidence ranges,
  and required version metadata before activation.
- Activation is an atomic SQLite transaction.
- Vector coverage is tracked separately and cannot block deterministic
  activation.
- Re-running a job with the same declared inputs is idempotent.
- A changed file causes only its affected files, symbols, relations, logical
  chunks, FTS projections, and necessary reverse relations to be recalculated.
- Unchanged content hashes reuse existing chunk and optional embedding records.
- Watcher event bursts are debounced and reconciled by a scan; filesystem event
  delivery alone is not repository truth.

## 10. Retrieval and Answer Pipeline

Implement one application-level pipeline shared by chat, CLI, REST, and MCP.

### 10.1 Query execution

1. Validate repository, conversation, user input, limits, and cancellation.
2. Resolve the active or explicitly requested snapshot.
3. Classify intent with deterministic rules first.
4. Plan the minimum retrieval channels needed.
5. Resolve exact paths and symbols before broader search.
6. Run lexical and bounded graph retrieval as appropriate.
7. Run Git-aware retrieval for change questions.
8. Optionally add semantic candidates when enabled and useful.
9. Deduplicate and fuse candidates without erasing derivation.
10. Expand only bounded graph neighborhoods.
11. Pack diverse evidence within explicit item and token limits.
12. Validate every evidence object against the selected snapshot.
13. Build a structured answer or finding contract.
14. Optionally generate a narrative using only verified evidence and warnings.
15. Validate claims and citations again.
16. Persist the message run, answer, evidence, warnings, and telemetry.
17. Stream typed progress and content events to the client.

### 10.2 Retrieval priority by intent

- Exact symbol/path: exact -> lexical fallback; no reranker.
- Callers/dependencies: exact -> graph; no LLM calculation.
- Change impact: Git diff -> syntax mapping -> graph -> tests/docs/rules.
- Configuration/schema lookup: exact/lexical -> stored relations.
- Conceptual repository question: exact -> lexical -> graph -> optional
  semantic -> optional reranking -> optional narrative.
- Trace-flow question: exact entry point -> bounded relation paths -> supporting
  lexical/semantic discovery -> verified narrative.

### 10.3 Performance controls

Every request must have:

- maximum query length;
- maximum result count per channel;
- graph depth and visited-node limits;
- maximum evidence items and bytes/tokens;
- parser, Git, storage, provider, and end-to-end timeouts;
- cooperative cancellation;
- bounded retries only for transient operations;
- no retry for validation, permission, or deterministic input errors;
- a request/correlation ID.

Avoid N+1 storage reads. Use indexed queries, batched entity hydration, query-plan
inspection for hot paths, and measured caching. Cache keys must include every
truth-bearing dimension, including repository, snapshot, normalized query,
retrieval policy, model/prompt version, and candidate digest where applicable.

## 11. Trust, Confidence, and Response Contracts

Use this controlled derivation enum:

| Class | Authority |
| --- | --- |
| `deterministic` | May support an authoritative finding |
| `static_resolved` | May support a finding with language limitations |
| `high_confidence_heuristic` | Labeled heuristic findings only |
| `low_confidence_heuristic` | Advisory discovery only |
| `semantic_candidate` | Candidate only without independent evidence |
| `model_generated` | Narrative only without supporting evidence |
| `unsupported` | Must abstain |

Confidence and derivation are separate fields.

### 11.1 Standard response envelope

All query adapters should serialize the same conceptual contract:

```json
{
  "contract_version": "1.0",
  "request_id": "opaque-id",
  "repository_id": "opaque-id",
  "snapshot": {
    "snapshot_id": "opaque-id",
    "git_head": "sha-or-null",
    "working_tree_fingerprint": "opaque-value",
    "freshness": "fresh",
    "semantic_coverage": 0.0
  },
  "answer": {
    "summary": "Verified answer or explicit abstention",
    "claims": [
      {
        "claim_id": "c1",
        "text": "Material factual claim",
        "derivation": "static_resolved",
        "confidence": 0.98,
        "evidence_ids": ["e1"]
      }
    ]
  },
  "evidence": [
    {
      "evidence_id": "e1",
      "file_path": "src/example.py",
      "symbol": "Example.run",
      "start_line": 10,
      "end_line": 18,
      "excerpt": "bounded display excerpt",
      "content_hash": "hash",
      "validation": "valid"
    }
  ],
  "warnings": [],
  "limitations": [],
  "timing_ms": {}
}
```

The exact schema belongs in versioned backend models and contract tests. The web
client consumes it; it does not redefine it.

### 11.2 Typed stream events

Use an explicit event schema:

- `run.accepted`
- `retrieval.started`
- `retrieval.progress`
- `evidence.available`
- `generation.delta`
- `answer.completed`
- `run.warning`
- `run.failed`
- `run.cancelled`
- `heartbeat`

Each event carries `contract_version`, `request_id`, `conversation_id`,
`message_id`, monotonically increasing `sequence`, timestamp, and typed payload.
Clients must safely ignore unknown future event types.

Streaming text is provisional. The final persisted response is authoritative.

## 12. REST API Surface

Use plural resource names, stable error codes, UTC timestamps, opaque IDs,
cursor pagination, explicit limits, and `/v1`.

### 12.1 Repositories

```text
POST   /v1/repositories
GET    /v1/repositories
GET    /v1/repositories/{repository_id}
DELETE /v1/repositories/{repository_id}
POST   /v1/repositories/{repository_id}/index
GET    /v1/repositories/{repository_id}/status
GET    /v1/repositories/{repository_id}/files
GET    /v1/repositories/{repository_id}/diagnostics
GET    /v1/repositories/{repository_id}/snapshots/active
GET    /v1/repositories/{repository_id}/semantic-status
```

### 12.2 Conversations

```text
POST   /v1/conversations
GET    /v1/conversations
GET    /v1/conversations/{conversation_id}
PATCH  /v1/conversations/{conversation_id}
DELETE /v1/conversations/{conversation_id}
GET    /v1/conversations/{conversation_id}/messages
POST   /v1/conversations/{conversation_id}/messages
GET    /v1/conversations/{conversation_id}/stream
POST   /v1/messages/{message_id}/retry
POST   /v1/message-runs/{run_id}/cancel
POST   /v1/messages/{message_id}/feedback
```

Prefer a single request that creates the user message and starts its run.
Return IDs immediately, then stream or poll status.

### 12.3 Repository intelligence

```text
POST   /v1/query
POST   /v1/query/stream
GET    /v1/evidence/{evidence_id}
GET    /v1/files/{file_id}
GET    /v1/symbols/{symbol_id}
GET    /v1/symbols/{symbol_id}/relations
GET    /v1/search/files
GET    /v1/search/symbols
GET    /v1/search/text
```

### 12.4 Change analysis

```text
POST   /v1/change-analysis/working-tree
POST   /v1/change-analysis/commits
GET    /v1/change-analysis/{analysis_id}
GET    /v1/change-analysis/{analysis_id}/report
```

### 12.5 Settings and providers

```text
GET    /v1/settings
PATCH  /v1/settings
GET    /v1/models
POST   /v1/models/test
POST   /v1/models/embedding-migrations
GET    /v1/models/embedding-migrations/{migration_id}
POST   /v1/models/embedding-migrations/{migration_id}/activate
```

Provider secrets never appear in GET responses, logs, browser storage, exported
history, or diagnostic bundles.

### 12.6 Error shape

Use one machine-readable envelope:

```json
{
  "error": {
    "code": "SNAPSHOT_NOT_READY",
    "message": "The repository snapshot is not ready for this operation.",
    "request_id": "opaque-id",
    "retryable": true,
    "details": {}
  }
}
```

Do not expose stack traces or filesystem secrets to the web client. Preserve
actionable diagnostics in local secured logs with redaction.

## 13. MCP and CLI Contracts

MCP and CLI must wrap the same use cases and produce the same evidence model.
Required MCP capabilities include:

- register/list/get repository;
- get repository and indexing status;
- resolve file or symbol;
- search files, symbols, and text;
- get callers, callees, dependencies, tests, and related documents;
- ask an evidence-grounded repository question;
- analyze working-tree or commit-range impact;
- retrieve evidence and reports.

Tool inputs and outputs must be bounded and versioned. A tool must return
warnings and unsupported states rather than silently omitting them.

The CLI should support scriptable JSON output and human-readable output.
Non-zero exit codes must distinguish invalid input, unavailable repository,
partial analysis, policy failure, and internal failure.

## 14. ChatGPT-Style Frontend Specification

The UI should feel polished, calm, fast, and familiar without copying protected
branding or exact visual assets.

### 14.1 Desktop layout

Use three coordinated regions:

1. **Left sidebar**
   - CodeAtlas mark and “New chat” action
   - active repository selector and index/freshness indicator
   - searchable conversation history grouped by relative date
   - rename, archive/delete, and optional pin actions
   - settings and sidebar collapse control

2. **Main conversation**
   - sticky compact header with repository, snapshot/freshness, and analysis mode
   - user and assistant turns in a readable centered column
   - streaming status such as “Resolving symbols” or “Checking callers”
   - structured answer sections, not an unbroken prose wall
   - inline citations that open evidence
   - retry, copy, feedback, and export actions
   - sticky composer with multiline input, send/cancel, mode selector, and
     optional change-preflight shortcut

3. **Evidence drawer/right rail**
   - opens from a citation or finding
   - file path, symbol, line range, derivation, confidence, snapshot
   - syntax-highlighted bounded source excerpt with cited lines emphasized
   - callers/callees, related tests/docs, or relation path when available
   - “open in editor” only through a safe local protocol or configured command

On medium screens, the evidence rail becomes an overlay. On mobile, the sidebar
and evidence drawer are separate full-height sheets.

### 14.2 Empty and onboarding states

The empty state must lead to value:

- if no repository exists, show “Add local repository” with privacy explanation;
- if indexing is pending, show real stage/progress/diagnostics;
- if ready, show prompt suggestions tied to the selected repository:
  “What changed?”, “Show likely impact”, “Find tests for…”, “Trace flow…”.

Do not fake analysis progress or display canned repository answers.

### 14.3 Message rendering

Assistant messages can include:

- concise answer summary;
- freshness banner when not fully fresh;
- findings grouped by severity;
- affected files and symbols;
- tests and documents;
- architecture-policy findings;
- limitations and warnings;
- collapsible evidence list;
- Markdown code blocks and safe tables.

Sanitize rendered Markdown and links. Repository content must never inject HTML,
scripts, styles, event handlers, or application instructions.

### 14.4 Visual system

- support light and dark themes;
- use restrained neutral surfaces with one configurable accent color;
- establish spacing, typography, radius, shadow, motion, and semantic status
  tokens;
- keep reading width comfortable while allowing structured reports to expand;
- use skeletons only for real pending data;
- keep motion subtle and honor reduced-motion preferences;
- never use color alone for freshness, confidence, severity, or error state;
- meet WCAG 2.2 AA for contrast, keyboard use, focus, labels, and screen readers.

### 14.5 Frontend correctness

- URL routes identify the active conversation.
- The server is the source of truth for history and message status.
- Optimistic UI may display a submitted user message, but must reconcile by ID.
- Reconnect resumes from the last stream sequence or fetches final message state.
- Duplicate events are ignored idempotently.
- Cancelling stops server work when possible and leaves an explicit state.
- Switching conversations cannot leak streamed content into another thread.
- Switching repositories requires a new conversation or explicit confirmed
  reassociation; never silently query a different repository in an old thread.
- Old citations retain their historical snapshot label.

## 15. Persistence and SQLite Rules

- Enable WAL mode and set a measured busy timeout.
- Keep write transactions short.
- Use a single writer/coordinator for high-volume index mutations when needed.
- Do not hold a transaction across parsing, Git, provider, network, or stream
  operations.
- Use foreign keys and integrity checks.
- Add indexes from measured access patterns, especially conversation ordering,
  snapshot membership, symbol lookup, path lookup, relation traversal, and jobs.
- Use explicit migrations; never mutate schema ad hoc at application startup.
- Migration upgrades and supported rollback/recovery paths require tests.
- Back up or checkpoint before destructive migrations.
- Store UTC timestamps and render locale/timezone in the client.
- Enforce stable sequence numbers for messages and stream events.
- Bound stored excerpts and diagnostics; do not duplicate the repository corpus
  into chat records.

## 16. Optional Semantic and Generation Layer

Do not begin here. Admit these features only after deterministic benchmarks pass.

### 16.1 Embeddings

- Cache by content hash, model ID, dimensions, and normalization version.
- Embed only changed unique retrieval content during normal updates.
- Keep active snapshot membership in SQLite authoritative.
- Use base and delta namespaces.
- A model upgrade creates a shadow namespace, asynchronously backfills, dual
  writes new changes, evaluates separately, atomically cuts over, and retains
  rollback.
- Never compare raw scores across embedding models.
- Report semantic coverage and partial freshness.

### 16.2 Reranking

Never rerank deterministic resolutions. Consider reranking only for ambiguous,
conceptual, mixed-candidate queries when evaluation proves an improvement.
Rerank a small bounded top-N set in one structured call.

### 16.3 Answer generation

The model receives only verified evidence, stored relation paths, deterministic
findings, and explicit warnings. It may explain or summarize; it may not invent
repository facts or calculate facts already available deterministically.

Provider usage requires repository-level opt-in, redaction/secret controls,
timeouts, retries, token and cost limits, usage telemetry, and deterministic
fallback.

## 17. Observability

Instrument:

- onboarding and repository registration;
- scanning, parsing, indexing, validation, activation, and recovery;
- query planning and every retrieval channel;
- graph depth, visited nodes, and truncation;
- evidence and claim validation;
- change analysis and report generation;
- conversation/message/run lifecycle;
- stream reconnect, cancellation, and failure;
- optional provider latency, retries, tokens, cost, and fallback.

Minimum dimensions include repository ID, snapshot ID, operation, intent,
counts, versions, duration, outcome, warning codes, and request ID.

Use hashed or opaque identifiers where practical. Do not record raw source,
prompts, excerpts, user questions, generated answers, secrets, or absolute local
paths by default.

## 18. Security Checklist

For every feature, consider:

- path traversal and canonicalization;
- symlink and Windows junction escape;
- reserved Windows names, case folding, long paths, UNC paths, and invalid
  Unicode;
- malformed parser input and denial-of-service limits;
- subprocess argument injection;
- SQL injection and unsafe dynamic FTS syntax;
- Markdown/HTML injection;
- prompt injection in repository content;
- secret leakage to providers, logs, exports, or browser storage;
- arbitrary file opening from evidence links;
- CORS and local-service exposure;
- unsafe deserialization;
- dependency and migration integrity;
- deletion and retention behavior.

Bind the local API to loopback by default. A change that exposes it to the
network requires authentication, authorization, CSRF/CORS review, threat-model
revision, and explicit approval.

## 19. Testing Strategy

No feature is complete with only happy-path unit tests.

### 19.1 Required test layers

- unit tests for pure domain logic;
- storage and migration tests against real SQLite;
- parser fixture and malformed-input tests;
- snapshot activation, rollback, crash, and stale-entity tests;
- API and MCP contract tests;
- retrieval evaluation cases;
- security tests;
- frontend component and accessibility tests;
- Playwright tests for critical user workflows;
- Windows-path tests and, before release, execution on Windows;
- performance tests for declared repository profiles.

Mock only external boundaries. Do not mock SQLite, parsers, or application
services in integration tests when the real local dependency is cheap.

### 19.2 Required fixture repositories

Maintain small, reviewable fixtures for:

- Python;
- TypeScript/JavaScript;
- Markdown/docs;
- configuration and schemas;
- mixed-language relationships;
- Git working-tree and commit-range changes;
- deleted/renamed files and symbols;
- parse failures and unsupported syntax;
- malicious paths/content;
- one-symbol incremental edits.

Each fixture must declare expected symbols, relations, evidence, changes,
warnings, and forbidden claims.

### 19.3 Initial release targets

| Metric | Target |
| --- | ---: |
| Valid file-and-line evidence | 100% |
| Active-snapshot leakage | 0 |
| Exact symbol lookup on fixtures | >= 98% |
| Changed-symbol precision/recall on supported fixtures | >= 95% |
| Direct dependency impact recall | >= 90% |
| Primary evidence Recall@10 | >= 90% |
| Unsupported factual claim rate | < 2% |
| Incremental indexing correctness | 100% on fixtures |
| Deterministic availability while semantic indexing lags | 100% |
| Contract-valid REST/MCP responses | 100% |
| Warm change-preflight p95 on declared target fixture | <= 10 s |
| Ordinary changed-file deterministic refresh p95 | <= 2 s |

Performance claims must name hardware, repository profile, cold/warm state, and
measurement method.

## 20. Development Order

Agents must deliver working vertical slices in this order. Do not scaffold all
phases at once.

### Canonical execution plan

All coding agents MUST coordinate through `docs/plans/PLAN.md`. That file is the
single source of truth for the active phase, active task, task status, and
handoff history. Detailed requirements for the active phase live in the linked
phase plan.

Execution is sequential:

- exactly one task may be `in_progress` or `verifying`;
- an agent MUST NOT begin a task whose dependencies are incomplete;
- an interrupted task is recovered in place after inspecting existing work;
- task completion requires current verification evidence in the handoff log;
- a phase remains `awaiting_user_approval` until the user explicitly approves
  its gate and an agent records that approval;
- `AGENTS.md` remains the stable policy authority and MUST NOT be used for live
  task status.

### Phase progress tracker

Update a phase to `[x]` only after every checklist item and its completion gate
have been satisfied with current verification evidence.

- [x] [Phase 0 — Product contract and evaluation](#phase-0--product-contract-and-evaluation)
- [ ] [Phase 1 — Repository truth vertical slice](#phase-1--repository-truth-vertical-slice)
- [ ] [Phase 2 — Snapshots, stable chunks, and lexical retrieval](#phase-2--snapshots-stable-chunks-and-lexical-retrieval)
- [ ] [Phase 3 — Polyglot graph and delivery contracts](#phase-3--polyglot-graph-and-delivery-contracts)
- [ ] [Phase 4 — Change assurance](#phase-4--change-assurance)
- [ ] [Phase 5 — Persistent ChatGPT-style web application](#phase-5--persistent-chatgpt-style-web-application)
- [ ] [Phase 6 — Continuous freshness and hardening](#phase-6--continuous-freshness-and-hardening)
- [ ] [Phase 7 — Measured semantic uplift](#phase-7--measured-semantic-uplift)

### Phase 0 — Product contract and evaluation

Build:

- [ ] Versioned domain, error, and evidence contracts
- [ ] Representative fixture repositories
- [ ] Evaluation runner and deterministic baseline
- [ ] ADR process and reproducible local development commands
- [ ] **Completion gate:** Metrics are reproducible, forbidden claims are
  tested, and the baseline results are recorded.

### Phase 1 — Repository truth vertical slice

Build:

- [ ] Windows-safe repository registration and scanning
- [ ] Ignore rules, classification, limits, and Git-state capture
- [ ] SQLite migrations and repository, snapshot, and file models
- [ ] Python symbol extraction through Tree-sitter plus `ast`
- [ ] Exact symbol lookup with validated file-and-line evidence
- [ ] Repository/index status API and minimal CLI
- [ ] Unit, integration, contract, security, and Windows-path tests for the
  vertical slice
- [ ] **Completion gate:** A local repository can be registered, indexed, and
  queried for an exact Python symbol through the application service, REST API,
  and CLI with valid snapshot-bound evidence.

Do not add embeddings, an LLM, MCP, or the full web UI.

### Phase 2 — Snapshots, stable chunks, and lexical retrieval

Build:

- [ ] Snapshot staging, validation, activation, and rollback
- [ ] Logical chunk identity, chunk versions, and snapshot membership
- [ ] Syntax-aware code and document chunks
- [ ] FTS5 plus exact and lexical search
- [ ] Incremental one-symbol edit behavior
- [ ] Crash, rollback, stale-entity, and incremental-reuse tests
- [ ] **Completion gate:** Unrelated chunks remain reusable after a one-symbol
  edit, interrupted indexing preserves the previous active snapshot, and stale
  entities cannot appear in active results.

### Phase 3 — Polyglot graph and delivery contracts

Build:

- [ ] TypeScript and JavaScript parsing
- [ ] Imports, calls, and other supported relations
- [ ] Bounded SQLite graph traversal
- [ ] Complete versioned REST and CLI adapters
- [ ] Initial versioned MCP adapters
- [ ] Evidence retrieval and cross-adapter contract suites
- [ ] **Completion gate:** Supported Python, TypeScript, and JavaScript symbols
  and relations resolve consistently through shared application services, and
  REST, CLI, and MCP outputs pass the same evidence-contract tests.

### Phase 4 — Change assurance

Build:

- [ ] Working-tree diff analysis
- [ ] Commit-range diff analysis
- [ ] Changed-symbol and public-contract detection
- [ ] Direct and bounded transitive impact analysis
- [ ] Related tests and documents
- [ ] Related configuration, schemas, and architecture rules
- [ ] Risk ordering
- [ ] JSON, Markdown, and SARIF reports
- [ ] Change-analysis evaluation and security tests
- [ ] **Completion gate:** The declared change-analysis fixtures meet the
  precision, recall, evidence-validity, snapshot-isolation, and performance
  targets in Section 19.3.

This phase proves the core product wedge.

### Phase 5 — Persistent ChatGPT-style web application

Build in vertical slices:

1. [ ] Repository onboarding, status, and diagnostics
2. [ ] Conversation schema and history API
3. [ ] Sidebar plus new, open, rename, archive, and delete conversation behavior
4. [ ] Submit message -> deterministic retrieval -> persisted answer
5. [ ] Typed SSE streaming, cancel, retry, and reconnect
6. [ ] Inline citations and evidence drawer
7. [ ] Change-preflight report experience
8. [ ] Settings, accessibility, responsive layout, and end-to-end tests

- [ ] **Completion gate:** Persistent history survives frontend and backend
  restarts; streaming is idempotent, cancellable, and reconnect-safe; citations
  retain their historical snapshot; and the critical workflows pass component,
  accessibility, responsive, and Playwright tests.

The first UI slice must use a real backend contract. Do not substitute fake chat
data for missing domain functionality.

### Phase 6 — Continuous freshness and hardening

Build:

- [ ] Reconciled and debounced filesystem watcher
- [ ] Crash recovery and actionable diagnostics
- [ ] Native packaging and installation workflow
- [ ] Upgrade and migration workflow
- [ ] Backup, restore, deletion, and support workflows
- [ ] Performance validation
- [ ] Security validation
- [ ] Windows release validation
- [ ] **Completion gate:** A packaged Windows build passes upgrade, recovery,
  backup/restore, deletion, security, performance, and end-to-end release tests
  without losing the last valid active snapshot or chat history.

### Phase 7 — Measured semantic uplift

Only after an approval gate:

- [ ] Explicit product, privacy, and architecture approval recorded
- [ ] Provider-neutral embedding interface
- [ ] Content-hash embedding cache
- [ ] LanceDB base/delta namespaces with authoritative SQLite membership
- [ ] Shadow embedding migration and atomic cutover/rollback
- [ ] Optional bounded reranking
- [ ] Optional evidence-grounded explanation
- [ ] Provider budgets, timeouts, retries, and cancellation
- [ ] Secret detection, redaction, and repository-level opt-in
- [ ] Provider telemetry without source, prompt, or answer content
- [ ] Deterministic fallback for disablement, failure, timeout, or budget
  exhaustion
- [ ] **Completion gate:** Every admitted semantic or generation feature shows
  measurable evaluation uplift over the deterministic baseline, preserves
  evidence and snapshot contracts, and passes privacy, fallback, and rollback
  tests.

Each optional feature needs evaluation showing measurable uplift over the
deterministic baseline.

## 21. Fast Delivery Without Fragility

“Quick” means shortening feedback loops, not skipping foundations.

Use these rules:

- implement the smallest end-to-end slice that produces verified user value;
- write contract and failure tests before or with implementation;
- use SQLite and in-process jobs before adding infrastructure;
- prefer deterministic templates before generation;
- use one canonical schema and generate adapters/types from it where practical;
- make expensive stages resumable and observable;
- keep optional providers behind interfaces and feature flags;
- measure before caching, parallelizing, or adding a database;
- leave no placeholder production path, fake success, swallowed exception, or
  unbounded operation;
- avoid premature framework abstractions, but extract a boundary when two real
  implementations or a testing need exists.

## 22. Coding-Agent Work Protocol

For every assignment:

1. Read this file and the directly relevant blueprint sections.
2. Inspect the existing tree, configuration, migrations, tests, and current Git
   diff before proposing changes.
3. Restate the user outcome, scope, affected boundaries, and acceptance tests.
4. Identify trust, freshness, Windows, security, migration, and compatibility
   risks.
5. Select the smallest vertical slice that can be completed and verified.
6. Add or update failing tests for the intended behavior.
7. Implement through domain/application layers, then adapters/UI.
8. Run targeted tests during development.
9. Run the repository’s required quality gates before claiming completion.
10. Review the diff for unrelated edits, secrets, generated files, debug code,
    silent failures, and stale documentation.
11. Report:
    - outcome;
    - important files changed;
    - migrations or contract changes;
    - commands/tests run and results;
    - remaining limitations or follow-up work.

Do not claim a test passed unless it was executed in the current environment.
If a required platform-specific check cannot run, state that precisely.

## 23. Definition of Done for Each Change

A change is complete only when:

- behavior satisfies explicit acceptance criteria;
- domain invariants still hold;
- input/output contracts are typed and validated;
- error and cancellation paths are implemented;
- storage changes include forward migration and migration tests;
- API/MCP changes include compatibility/contract tests;
- UI changes include loading, empty, success, error, retry, keyboard, and
  responsive states as relevant;
- security and privacy implications are addressed;
- observability exposes outcome without leaking content;
- tests pass at the appropriate layers;
- documentation and examples are current;
- no unrelated scope was introduced.

## 24. Pull-Request Checklist

```text
[ ] User outcome and supported scope are explicit
[ ] Local-first behavior preserved
[ ] No unnecessary service, database, or framework introduced
[ ] Windows path/process behavior considered
[ ] Repository code is never executed during indexing
[ ] Snapshot consistency and rollback preserved
[ ] Indexing remains incremental and idempotent
[ ] Exact source lines and evidence validation preserved
[ ] Derivation and confidence remain distinct
[ ] Deterministic behavior works without embeddings or an LLM
[ ] SQLite transactions are short and migrations are tested
[ ] API/MCP/UI use shared application services
[ ] Chat history is persisted and snapshot-bound
[ ] Streaming is idempotent, cancellable, and reconnect-safe
[ ] Prompt/HTML/path/subprocess injection considered
[ ] Secrets and source content are absent from logs
[ ] Retrieval or impact evaluation updated when behavior changes
[ ] Unit, integration, contract, failure, and relevant E2E tests included
[ ] Documentation and ADRs updated
[ ] Verification commands and actual results recorded
```

## 25. Scope Changes Requiring Explicit Approval

Do not introduce any of the following without a documented user need, benchmark
or discovery evidence, security/operational impact, migration and rollback plan,
and explicit approval:

- mandatory cloud dependency;
- microservice or message broker;
- new primary database;
- network exposure beyond loopback;
- multi-user authentication or tenancy;
- autonomous source modification;
- full IDE/Monaco experience;
- new programming-language support;
- Git hosting or CI integration;
- repository content transmission enabled by default;
- LLM authority over deterministic findings;
- breaking API, MCP, evidence, snapshot, or persistence contract.

## 26. First Recommended Assignment

When implementation has not started, begin with:

> Build a local-only vertical slice that registers a Windows repository, applies
> path-safety and ignore rules, records Git state, creates and activates a
> versioned SQLite snapshot, extracts Python symbols using Tree-sitter and
> Python AST, and resolves an exact symbol with verified file-and-line evidence
> through both application service and `/v1` REST endpoint. Include migrations,
> fixture repositories, unit/integration/contract/security tests, diagnostics,
> and a reproducible development command. Do not add embeddings, an LLM, MCP,
> or the browser UI in this assignment.

After that slice passes its release gate, proceed through the development order
in Section 20.

## 27. Final Product Test

Before accepting any feature, ask:

- Does it make repository truth more accurate, current, or usable?
- Can a developer or coding agent verify the output?
- Does it improve change assurance or only add surface area?
- Does it still work when optional model services are absent?
- Does the UI expose evidence and uncertainty instead of hiding them?
- Is the implementation small enough to understand, test, recover, and evolve?

If the answer to these questions is unclear, reduce scope and strengthen the
contract before adding sophistication.
