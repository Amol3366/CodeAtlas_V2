# Phase 5 — Persistent ChatGPT-Style Web Application

Status: `complete` (gate approved by the user 2026-07-28, with three of the
eight conditions reported as only partly met — no Playwright suites exist —
and accepted on that basis. The gap carries into Phase 6.)
Gate authority: user
Prerequisites: Phase 4 approved; `AGENTS.md` Sections 8.2, 11, 12.2, 14, 15;
the blueprint

## Outcome

A developer opens a local web application, adds a repository, watches real
indexing progress, and then asks questions in a persistent ChatGPT-style
conversation. Every answer is the same deterministic, evidence-backed contract
the CLI, REST, and MCP already produce — rendered with inline citations that
open an evidence drawer showing the exact cited lines, their derivation,
confidence, and the snapshot they were true against. Conversations survive
frontend and backend restarts; streaming is idempotent, cancellable, and
reconnect-safe; a change-preflight report is one click away.

The chat interface is an access surface for verified repository intelligence
(`AGENTS.md` Section 2). It must not weaken the evidence, freshness, or
abstention contracts — and because no LLM is admitted before Phase 7, every
assistant message in Phase 5 is a deterministic structured answer rendered
readably, never generated prose.

## Completion Gate (from `AGENTS.md` Sections 20 and 19.3)

Phase 5 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log.

| # | Gate condition | Measured against |
| --- | --- | --- |
| 1 | Persistent history survives frontend restart, backend restart, and both | Playwright restart test + storage integration tests |
| 2 | Streaming is idempotent (duplicate events ignored), cancellable (server work stops, state explicit), and reconnect-safe (resume from last sequence or final state) | SSE contract tests + Playwright reconnect test |
| 3 | A historical message's citations retain their historical snapshot label; reopening history never relabels old evidence as current | contract + component tests |
| 4 | Creating a user message and its queued run is transactional; completed assistant text and evidence links commit atomically; failed/cancelled runs remain visible and retryable | storage integration tests |
| 5 | Contract-valid REST responses 100%; stream events all schema-valid with monotonic sequences | contract suite |
| 6 | Valid file-and-line evidence 100% in conversation answers; active-snapshot leakage 0 | evidence validation tests |
| 7 | Critical workflows pass component, accessibility (axe, keyboard), responsive, and Playwright end-to-end tests | frontend suites |
| 8 | Phase 1–4 baselines still reproduce (`--check`) and the full backend gate stays green | existing gate scripts |

A missed target is reported as missed, with the measurement and the reason.

## What Phase 4 Leaves in Place (build on, do not duplicate)

| Asset | Location | Phase 5 relevance |
| --- | --- | --- |
| Repository registration, indexing, status, diagnostics services | `application/` | slice 1's UI consumes these endpoints unchanged |
| Exact symbol, lexical search, graph query services | `application/` | the deterministic retrieval channels behind every conversation answer |
| `ChangeAnalysisService` + JSON/Markdown/SARIF reports | `application/change_analysis.py`, `delivery/` | the change-preflight experience renders these |
| `EvidenceBuilder` (hash-verified, snapshot-bound, drift-aware) | `application/evidence.py` | message evidence uses the same builder; no chat-only evidence path |
| Response envelope contract (`answer`, `claims`, `evidence`, `warnings`) | `contracts.py`, `docs/api/contract-v1.schema.json` | the web client consumes it; it does not redefine it |
| Error envelope, HTTP/CLI code tables | `api/errors.py`, `domain/errors.py` | new codes extend the same tables |
| Migrations `0001`–`0007`, WAL, short transactions | `storage/sqlite/` | Phase 5 adds `0008`; earlier migrations are never edited |
| Cross-adapter equivalence pattern | `tests/contract/` | conversation answers must equal the `/v1/query` answer for the same question |

## Global Constraints

Phase 1–4 constraints all still apply. Additions and emphases:

- **No LLM, no embeddings.** Every assistant message is a deterministic
  structured answer or an explicit abstention. Deterministic templates render
  summaries; nothing invents repository facts (`AGENTS.md` Section 16 is
  Phase 7's, not Phase 5's).
- **The backend owns conversations.** SQLite is the authoritative store for
  conversations, messages, runs, and evidence links. The frontend caches; it
  never becomes the source of truth (`AGENTS.md` Section 6.2).
- **One pipeline.** A conversation answer is produced by the same application
  services the CLI, REST `/v1/query`, and MCP use. No chat-only retrieval
  logic, no duplicated repository logic in the web adapter.
- **Snapshot binding.** Every `MessageRun` records the snapshot it answered
  against. Historical messages keep that label forever; freshness banners
  describe the run's snapshot, never silently the current one.
- **Streaming text is provisional; the persisted response is authoritative**
  (`AGENTS.md` Section 11.2). The client reconciles streamed content against
  the final stored message by ID.
- **Repository content is untrusted in the browser too.** Rendered Markdown is
  sanitized; repository text can never inject HTML, scripts, styles, event
  handlers, or application instructions (`AGENTS.md` Section 14.3). Evidence
  excerpts render as text in code blocks, never as HTML.
- **Loopback only.** The API stays bound to loopback; CORS allows only the
  local dev origin during development. Serving the built app cross-network is
  out of scope (Section 25 approval boundary).
- **UTC in storage, locale in the client.** Conversation ordering uses backend
  timestamps and stable pagination (`AGENTS.md` Section 8.2).
- Migrations are forward-only and additive. `0001`–`0007` MUST NOT be edited;
  Phase 5 adds `0008`.
- Exactly one task may be `in_progress` or `verifying`.
- Test-first: write the failing test, observe it fail, then implement.

## Non-Goals (explicitly deferred)

| Deferred item | Phase |
| --- | --- |
| LLM narrative answers, reranking, embeddings, provider settings UI beyond placeholders | 7 |
| Filesystem watcher, packaging the web app into the native install, auto-start | 6 |
| Model-generated conversation titles (deterministic titles only) | 7 |
| Multi-user, auth, tenancy, network exposure | out of MVP scope |
| WebSockets (SSE only; bidirectional need unproven) | out of scope until proven |
| Full IDE/Monaco editing experience | out of scope (Section 25) |
| "Open in editor" protocol handler | 6 (packaging concern; UI shows the affordance disabled with a tooltip) |
| Export/import of chat history | 6 backup/restore workflow |
| Message feedback analytics (feedback is stored, not analyzed) | later |

## Phase Architecture Decisions

Fixed for Phase 5 so tasks compose. Deviation requires an ADR and user
approval. ADR-0006 (P5-SETUP) records decisions 1–10.

### 1. Conversation persistence model (migration `0008`)

`SCHEMA_VERSION` 7 → 8, additive, forward-only:

```text
conversations(conversation_id PK, repository_id FK CASCADE, title,
              pinned_snapshot_policy NULL, created_at, updated_at,
              last_message_at NULL, archived_at NULL, deleted_at NULL)
messages(message_id PK, conversation_id FK CASCADE, role, status,
         sequence_number, content, error_code NULL,
         created_at, completed_at NULL,
         UNIQUE(conversation_id, sequence_number))
message_runs(run_id PK, message_id FK CASCADE, repository_id, snapshot_id,
             normalized_query, intent, retrieval_policy_version,
             status, latency_ms NULL, warnings_json, created_at,
             completed_at NULL)
message_evidence(message_id FK CASCADE, evidence_id, citation_ordinal,
                 claim_ids_json, file_path, symbol NULL, start_line, end_line,
                 content_hash, derivation, confidence, snapshot_id,
                 PRIMARY KEY(message_id, citation_ordinal))
message_feedback(message_id FK CASCADE, rating, reason_code NULL,
                 comment NULL, created_at, PRIMARY KEY(message_id))
```

- Deleting a conversation is **soft** (`deleted_at`), recoverable until
  Phase 6's retention workflow; deleting a repository **cascades** — the
  Section 8.2 "explicit policy" is: repository deletion removes its
  conversations, stated in the confirmation dialog.
- `message_evidence` snapshots the evidence *fields* (path, range, hash,
  snapshot ID) rather than joining live index tables, because a historical
  message must keep telling the truth it told after the snapshot is
  superseded — the same audit rule migration `0007` established for analyses.
- Bounded columns: `content` ≤ 64 KiB, warnings JSON ≤ 8 KiB; the repository
  corpus is never duplicated into chat rows (`AGENTS.md` Section 15).
- Indexes: `conversations(repository_id, last_message_at DESC)`,
  `messages(conversation_id, sequence_number)`, `message_runs(message_id)`.

### 2. Transactional lifecycle

```text
POST message:  [tx] insert user message (status complete)
                    + assistant message (status queued)
                    + run (status queued)          → returns all three IDs
run executes:  status retrieving → generating (in-memory, evented)
completion:    [tx] update assistant message (content, status complete,
                    completed_at) + insert message_evidence rows
                    + update run (status complete, latency)
failure:       [tx] assistant message status failed + error_code; run failed
cancel:        cooperative flag → [tx] status cancelled; partial text discarded
retry:         [tx] new run for the same assistant message, prior run kept
```

One in-process worker executes runs (single-user product; no broker —
`AGENTS.md` Section 4.5). Runs are executed by an `asyncio` task owned by the
API process; the CLI/REST `/v1/query` path stays synchronous and unchanged.

### 3. The deterministic answer pipeline

`AnswerPipeline.execute(repository_id, conversation_id, text, cancel_token)`
implements `AGENTS.md` Section 10.1 steps 1–13 and 16–17 (no generation):

1. Validate input, length ≤ 4,000 chars, resolve active snapshot.
2. Classify intent with deterministic rules, in order: exact symbol/path
   reference → callers/dependencies phrasing → change/impact phrasing →
   text-search phrasing → fallback `lexical`.
3. Run only the channels the intent needs (exact → graph → lexical → Git),
   through the existing application services.
4. Build the Section 11.1 envelope: claims with derivation and confidence,
   evidence through `EvidenceBuilder`, warnings, limitations.
5. Render `summary` and the assistant Markdown from deterministic templates
   (fixed strings + validated values only — no free-form interpolation of
   repository text outside code spans).
6. Unsupported question → explicit abstention with the reason and what *can*
   be asked.

The pipeline emits typed progress events through a callback; it never touches
HTTP. Contract tests assert a conversation answer equals the `/v1/query`
answer for the same question against the same snapshot.

### 4. Typed SSE streaming

- Endpoint: `GET /v1/conversations/{id}/stream` (SSE, hand-rolled over
  FastAPI's `StreamingResponse`; no new dependency — recorded in ADR-0006).
- Events exactly per `AGENTS.md` Section 11.2: `run.accepted`,
  `retrieval.started`, `retrieval.progress`, `evidence.available`,
  `generation.delta` (template-rendered sections in Phase 5),
  `answer.completed`, `run.warning`, `run.failed`, `run.cancelled`,
  `heartbeat` (every 15 s).
- Every event carries `contract_version`, `request_id`, `conversation_id`,
  `message_id`, monotonically increasing `sequence`, UTC timestamp, typed
  payload. SSE `id:` is the sequence, so `Last-Event-ID` resumes.
- Replay: a bounded in-memory ring buffer (last 256 events per active run).
  A reconnect inside the buffer replays from the requested sequence; outside
  it (or after completion) the client fetches the final message state — both
  paths are contract-tested. Events are not persisted; the persisted message
  is the authority.
- Unknown future event types must be ignored by the client (tested with a
  synthetic event).

### 5. Frontend stack (the ADR-0006 headline)

| Concern | Choice | Why |
| --- | --- | --- |
| Build | Vite + React 18 + TypeScript strict | `AGENTS.md` Section 6.2 |
| Package manager | pnpm, `apps/web/pnpm-lock.yaml` committed | blueprint tree |
| Styling | Tailwind CSS + CSS custom-property design tokens | utility CSS; tokens give light/dark and the single accent |
| Accessible primitives | Radix UI primitives (dialog, dropdown, tooltip) only | headless, WCAG-friendly, no visual framework lock-in |
| Server state | TanStack Query | Section 6.2 |
| Routing | react-router; `/conversations/:conversationId` identifies the thread | Section 14.5 "URL routes identify the active conversation" |
| Local UI state | React state + one small store (Zustand) only for layout/panels | "small local UI-state store only where React state is insufficient" |
| API types | `openapi-typescript` generated from FastAPI's OpenAPI into `apps/web/src/lib/api-types.gen.ts`, checked in, `--check` script | "generated or centrally defined API types" |
| Markdown | `react-markdown` + `rehype-sanitize` (strict schema, no raw HTML) | Section 14.3 sanitization |
| Component tests | Vitest + Testing Library + `vitest-axe` | Section 6.2 |
| E2E | Playwright against the real backend on a temp database | Section 6.2 |

Node 20 LTS + pnpm become documented Windows dev prerequisites in the README
and `scripts/setup_windows.ps1`.

### 6. Frontend correctness rules (Section 14.5, made testable)

- The server is the source of truth; TanStack Query caches keyed by
  conversation ID; switching conversations cancels in-flight stream
  subscriptions so streamed content cannot leak across threads (tested).
- Optimistic user message shows immediately with a client key, reconciled by
  server ID on the POST response; duplicates impossible by key (tested).
- Stream consumption is idempotent: events with `sequence` ≤ last applied are
  dropped (tested with deliberate duplicates).
- Cancel issues `POST /v1/message-runs/{run_id}/cancel`, then trusts the
  terminal event/state; the UI never fakes a cancelled state ahead of the
  server.
- A historical message renders its own `snapshot_id` label and a "not
  current" freshness badge when it differs from the active snapshot.
- Switching repositories requires a new conversation; the composer for an
  existing thread is locked to its repository (Section 14.5).

### 7. Desktop-first layout with responsive sheets

Three regions per Section 14.1: sidebar (repository selector + freshness,
searchable date-grouped history, new chat, settings), conversation column
(sticky header with repository/snapshot/mode, turns, streaming status,
sticky composer), evidence rail (opens from citations; overlay on medium
screens; full-height sheet plus separate sidebar sheet on mobile). Reduced
motion honored; never color alone for status; WCAG 2.2 AA is a gate item,
not a polish item.

### 8. Deterministic conversation titles

Title = first user message, normalized and truncated at a word boundary
≤ 60 chars ("deterministic initially; model-generated titles are optional and
non-authoritative" — Section 8.2). Rename is always available.

### 9. Serving model

Development: Vite dev server proxies `/v1` to the loopback API
(`scripts/run_dev.ps1` starts both). The production static-serving story
(FastAPI `StaticFiles` mount) is built and tested behind `codeatlas serve
--web`, but packaging/installation remains Phase 6.

### 10. Version constants and error codes

| Constant / code | Value | Effect |
| --- | --- | --- |
| `SCHEMA_VERSION` | `7 → 8` | migration `0008` (P5-01) |
| `CONVERSATION_NOT_FOUND` | new | HTTP 404, CLI 3 |
| `MESSAGE_NOT_FOUND` | new | HTTP 404, CLI 3 |
| `RUN_NOT_CANCELLABLE` | new | HTTP 409, CLI 3 |
| `RUN_NOT_RETRYABLE` | new | HTTP 409, CLI 3 |
| `CONVERSATION_ARCHIVED` | new | HTTP 409, CLI 3 |
| `QUERY_TOO_LONG` | new | HTTP 422, CLI 2 |

`contract_version` stays `"1.0"`; the contract gains additive
`conversation`, `message`, `message_run`, and `stream_event` schemas, and
`docs/api/contract-v1.schema.json` is regenerated.

### Module map additions

```text
src/codeatlas/
├── domain/
│   └── conversations.py        # ConversationRecord, MessageRecord, RunRecord,
│                               #   roles/status enums, sequence rules
├── conversations/
│   ├── __init__.py
│   ├── intent.py               # deterministic intent rules (ordered, versioned)
│   ├── pipeline.py             # AnswerPipeline over existing app services
│   ├── templates.py            # deterministic summary/section rendering
│   └── events.py               # typed stream event models + ring buffer
├── application/
│   └── conversation_service.py # lifecycle, transactions, run execution, cancel/retry
├── api/routers/
│   ├── conversations.py        # Section 12.2 endpoints
│   └── stream.py               # SSE endpoint
└── storage/sqlite/
    ├── migrations/0008_phase5_conversations.sql
    └── stores.py               # + ConversationStore

apps/web/
├── package.json, pnpm-lock.yaml, vite.config.ts, tsconfig.json
├── index.html
└── src/
    ├── app/                    # providers, router, theme, query client
    ├── lib/                    # api client, api-types.gen.ts, sse client, sanitize schema
    ├── components/             # primitives: Button, Dialog, Markdown, Skeleton…
    ├── features/
    │   ├── repositories/       # onboarding, status, diagnostics
    │   ├── conversations/      # sidebar, thread, composer, message rendering
    │   ├── evidence/           # citations, drawer
    │   ├── change-analysis/    # preflight experience
    │   └── settings/
    ├── routes/
    └── styles/                 # tokens.css, tailwind entry
```

## Task Board

| Task | Deliverable | Dependencies | Status |
| --- | --- | --- | --- |
| P5-SETUP | ADR-0006, error codes, contract models, schema regen | Phase 4 approval + this plan approved | `complete` |
| P5-01 | Migration `0008`, conversation domain, `ConversationStore` | P5-SETUP | `complete` |
| P5-02 | Conversation/message REST: CRUD, pagination, rename/archive/delete | P5-01 | `complete` |
| P5-03 | Intent rules, `AnswerPipeline`, deterministic templates, run execution | P5-01 | `complete` |
| P5-04 | Typed SSE, cancel, retry, reconnect, replay buffer | P5-02, P5-03 | `complete` |
| P5-05 | Web scaffold: Vite/React/Tailwind/Query/router, generated types, tokens, shell | P5-SETUP | `complete` |
| P5-06 | Repository onboarding, status, diagnostics UI (first real-backend slice) | P5-05 | `complete` |
| P5-07 | Sidebar + conversation management UI | P5-02, P5-05 | `complete` |
| P5-08 | Thread view: submit, stream, cancel/retry, sanitized rendering | P5-04, P5-07 | `complete` |
| P5-09 | Inline citations, evidence drawer, change-preflight experience | P5-08 | `complete` |
| P5-10 | Settings, accessibility, responsive, Playwright, docs, phase gate | P5-06, P5-09 | `complete` |

---

## P5-SETUP — ADR, Error Codes, Contract Models

**Files**

- Create: `docs/adr/0006-web-application-design.md`
- Modify: `src/codeatlas/domain/errors.py`, `src/codeatlas/api/errors.py`,
  `src/codeatlas/cli/main.py` (six new codes per decision 10)
- Modify: `src/codeatlas/contracts.py` (additive: `Conversation`, `Message`,
  `MessageRun`, `StreamEvent` envelope + per-type payloads,
  `ConversationPage`, `MessagePage`)
- Modify: `src/codeatlas/schema_export.py`,
  `docs/api/contract-v1.schema.json` (regenerated),
  `tests/contract/test_schema_export.py`
- Create: `tests/contract/test_conversation_contract.py`,
  `tests/contract/test_conversation_errors.py`

**Interfaces**

- Produces: `contracts.Conversation`, `contracts.Message`
  (`role: user|assistant|system_event`,
  `status: queued|retrieving|generating|complete|failed|cancelled`),
  `contracts.StreamEvent` with `sequence: int`, `event: str`, typed payload
  union — every later task imports these names.

**Steps**

- [ ] **Step 1: Write ADR-0006** covering decisions 1–10 (persistence model,
  transactional lifecycle, deterministic pipeline, SSE design, the full
  frontend stack table with the new dependency surface, serving model,
  soft-delete/cascade policy, deterministic titles).
- [ ] **Step 2: Write the failing contract and error-code tests**, mirroring
  `tests/contract/test_change_analysis_errors.py`.
- [ ] **Step 3: Add the error codes and contract models** (frozen,
  `extra="forbid"`), regenerate the schema, drive the tests green.
- [ ] **Step 4: Run the full gate and append the handoff.**

**Acceptance**

- New models round-trip; schema export is current; nothing existing breaks.
- ADR-0006 names every new runtime and dev dependency the web app introduces.

---

## P5-01 — Migration 0008, Domain, ConversationStore

**Files**

- Create: `src/codeatlas/storage/sqlite/migrations/0008_phase5_conversations.sql`
- Create: `src/codeatlas/domain/conversations.py`
- Modify: `src/codeatlas/storage/sqlite/migrations.py` (`SCHEMA_VERSION = 8`),
  `src/codeatlas/storage/sqlite/stores.py` (`ConversationStore`)
- Create: `tests/integration/test_conversation_store.py`
- Modify: `tests/integration/test_migrations.py` (v7→v8 upgrade preserves rows)

**Interfaces**

- Produces:

```python
class ConversationStore:
    def create_conversation(self, record: ConversationRecord) -> None
    def list_conversations(self, repository_id, *, cursor, limit, include_archived) -> Page[ConversationRecord]
    def get_conversation(self, conversation_id) -> ConversationRecord | None
    def rename / archive / soft_delete(self, conversation_id, ...) -> None
    def create_user_turn(self, user: MessageRecord, assistant: MessageRecord, run: RunRecord) -> None   # one tx
    def complete_assistant(self, message_id, content, evidence: Sequence[EvidenceRow], run_id, latency_ms) -> None  # one tx
    def fail_or_cancel(self, message_id, run_id, status, error_code) -> None
    def create_retry_run(self, message_id, run: RunRecord) -> None
    def list_messages(self, conversation_id, *, cursor, limit) -> Page[MessageRecord]
    def get_evidence(self, message_id) -> tuple[EvidenceRow, ...]
```

**Steps**

- [ ] **Step 1: Write the failing store tests**: sequence numbers unique and
  monotonic per conversation; `create_user_turn` is atomic (a forced failure
  inserts nothing); `complete_assistant` is atomic; soft delete hides from
  listing but preserves rows; repository deletion cascades; a v7 database
  upgrades in place with rows intact; timestamps are UTC; content over the
  bound is rejected.
- [ ] **Step 2: Implement** the migration, domain records, and store.
- [ ] **Step 3: Run the gate and append the handoff.**

**Acceptance**

- Every Section 8.2 "required behavior" line that is storage-shaped has a
  direct test; transactions are short (no parse/Git/stream work inside).

---

## P5-02 — Conversation and History REST

**Files**

- Create: `src/codeatlas/api/routers/conversations.py`
- Create: `src/codeatlas/application/conversation_service.py` (lifecycle
  half; run execution arrives in P5-03)
- Modify: `src/codeatlas/application/container.py`, `src/codeatlas/api/app.py`
- Create: `tests/contract/test_conversations_api.py`

**Interfaces**

- Consumes: `ConversationStore` (P5-01), contract models (P5-SETUP).
- Produces the Section 12.2 subset:
  `POST/GET /v1/conversations`, `GET/PATCH/DELETE /v1/conversations/{id}`,
  `GET /v1/conversations/{id}/messages` — cursor pagination, stable ordering,
  opaque cursors; `POST …/messages`, retry, cancel, feedback, and stream land
  in P5-03/P5-04.

**Steps**

- [ ] **Step 1: Write the failing contract tests**: create requires a valid
  repository; listing orders by `last_message_at` with a stable cursor;
  PATCH renames; DELETE soft-deletes; archived conversations reject new
  messages with `CONVERSATION_ARCHIVED`; unknown IDs map to
  `CONVERSATION_NOT_FOUND`; error envelope shape matches Section 12.6.
- [ ] **Step 2: Implement** the service methods and thin router.
- [ ] **Step 3: Run the gate and append the handoff.**

**Acceptance**

- 100% of responses validate against the exported contract schemas.

---

## P5-03 — Deterministic Answer Pipeline and Run Execution

**Files**

- Create: `src/codeatlas/conversations/__init__.py`,
  `src/codeatlas/conversations/intent.py`,
  `src/codeatlas/conversations/pipeline.py`,
  `src/codeatlas/conversations/templates.py`
- Modify: `src/codeatlas/application/conversation_service.py` (submit,
  execute, cancel, retry), `src/codeatlas/api/routers/conversations.py`
  (`POST …/messages`, `POST /v1/messages/{id}/retry`,
  `POST /v1/message-runs/{id}/cancel`, `POST /v1/messages/{id}/feedback`)
- Create: `tests/unit/test_intent_rules.py`,
  `tests/unit/test_answer_templates.py`,
  `tests/integration/test_answer_pipeline.py`,
  `tests/contract/test_conversation_query_parity.py`

**Interfaces**

- Consumes: exact/graph/lexical/change application services; `EvidenceBuilder`.
- Produces:

```python
class AnswerPipeline:
    def execute(self, request: AnswerRequest, on_event: Callable[[PipelineEvent], None],
                cancel: CancelToken) -> AnswerResult   # envelope + rendered markdown
```

**Steps**

- [ ] **Step 1: Write the failing intent tests**: a symbol-shaped query routes
  exact-first; "who calls X" routes graph; "what changed" routes change;
  free text routes lexical; each rule names its version
  (`retrieval_policy_version = "5.0"`); over-long input →`QUERY_TOO_LONG`.
- [ ] **Step 2: Write the failing template tests**: rendered Markdown contains
  repository text only inside code spans/fences; the abstention template
  names what was tried; every material claim carries evidence IDs.
- [ ] **Step 3: Implement intent rules, pipeline, templates.**
- [ ] **Step 4: Write the failing parity test** — the same question through
  the conversation pipeline and through `/v1/query` yields the same claims,
  evidence IDs, and warnings against the same snapshot — then wire run
  execution (queued → retrieving → generating → complete) with cooperative
  cancellation checkpoints between channels.
- [ ] **Step 5: Run the gate and append the handoff.**

**Acceptance**

- Answers are byte-stable across two runs on an unchanged snapshot.
- A failed run leaves the user message visible and the assistant message
  `failed` with a retryable error code; retry creates a new run and preserves
  the old one.

---

## P5-04 — Typed SSE Streaming, Cancel, Reconnect

**Files**

- Create: `src/codeatlas/conversations/events.py`,
  `src/codeatlas/api/routers/stream.py`
- Modify: `src/codeatlas/application/conversation_service.py` (event
  emission), `src/codeatlas/api/app.py`
- Create: `tests/contract/test_stream_events.py`,
  `tests/integration/test_stream_lifecycle.py`

**Interfaces**

- Consumes: `AnswerPipeline` events (P5-03).
- Produces: `GET /v1/conversations/{id}/stream` emitting the Section 11.2
  event set; ring buffer `EventBuffer(capacity=256)` with
  `replay_from(sequence)`.

**Steps**

- [ ] **Step 1: Write the failing event-schema tests**: every event validates;
  sequences strictly increase; heartbeat arrives on an idle stream; SSE `id:`
  equals sequence.
- [ ] **Step 2: Write the failing lifecycle tests** (httpx ASGI streaming):
  a submitted message streams `run.accepted → retrieval.* →
  evidence.available → generation.delta → answer.completed`; cancel mid-run
  yields `run.cancelled` and a `cancelled` persisted message; reconnect with
  `Last-Event-ID` inside the buffer replays exactly the missed events;
  reconnect after completion returns the final state path; duplicate delivery
  is harmless.
- [ ] **Step 3: Implement** the buffer, the SSE endpoint, and event wiring.
- [ ] **Step 4: Run the gate and append the handoff.**

**Acceptance**

- Gate condition 2 is fully covered by tests at this layer, before any UI
  exists.

---

## P5-05 — Web Application Scaffold

**Files**

- Create: `apps/web/package.json`, `pnpm-lock.yaml`, `vite.config.ts`,
  `tsconfig.json`, `index.html`, `.gitignore`
- Create: `apps/web/src/app/` (providers, router, query client, theme),
  `apps/web/src/styles/tokens.css`, `apps/web/src/lib/api.ts`,
  `apps/web/src/lib/sse.ts`, `apps/web/src/lib/sanitize.ts`,
  `apps/web/src/lib/api-types.gen.ts` (generated)
- Create: `scripts/generate_web_types.ps1` (+ `--check` mode),
  update `scripts/run_dev.ps1`
- Create: `apps/web/src/components/` primitives with tests
  (`Button`, `Dialog`, `Markdown`, `Skeleton`, `VisuallyHidden`)
- Modify: `README.md` (Node 20 + pnpm prerequisites),
  `scripts/setup_windows.ps1`

**Steps**

- [ ] **Step 1: Scaffold** Vite + React + TS strict + Tailwind + tokens
  (light/dark via `prefers-color-scheme` and a manual toggle; single accent
  custom property; semantic status tokens that never rely on color alone).
- [ ] **Step 2: Implement type generation**: FastAPI app exports OpenAPI to
  disk; `openapi-typescript` emits `api-types.gen.ts`; the `--check` mode
  fails when stale (same discipline as the contract schema export).
- [ ] **Step 3: Write failing component tests** for the `Markdown` primitive:
  script tags, event handlers, raw HTML, `javascript:` links, and style
  injection are all stripped; code blocks render as text; then implement with
  `react-markdown` + `rehype-sanitize` strict schema.
- [ ] **Step 4: Implement the SSE client** (`EventSource` wrapper with
  last-sequence tracking, duplicate drop, reconnect backoff) with unit tests
  against a mocked stream.
- [ ] **Step 5: App shell**: three-region layout, responsive breakpoints,
  skeleton states, error boundary, router with `/` and
  `/conversations/:conversationId`.
- [ ] **Step 6: Run lint/type/test for the web package** (`pnpm lint`,
  `pnpm typecheck`, `pnpm test`), the backend gate, and append the handoff.

**Acceptance**

- `pnpm build` produces a working bundle; `run_dev.ps1` starts API + web with
  a working proxy; the sanitizer test suite passes; generated types match the
  live OpenAPI.

---

## P5-06 — Repository Onboarding, Status, Diagnostics UI

**Files**

- Create: `apps/web/src/features/repositories/` (RepositoryPicker,
  AddRepositoryDialog, IndexStatusPanel, DiagnosticsPanel + tests)
- Create: `apps/web/src/routes/onboarding.tsx`

**Interfaces**

- Consumes: existing `/v1/repositories*` endpoints only — this is the "first
  UI slice uses a real backend contract" requirement; no fake data.

**Steps**

- [ ] **Step 1: Write failing component tests**: empty state leads to "Add
  local repository" with the privacy explanation; a registered repository
  shows real stage/progress/diagnostics from the status endpoint; failure
  states render the error envelope's message and code; polling stops on
  terminal states.
- [ ] **Step 2: Implement** with TanStack Query polling (status interval
  while indexing, off when active/failed).
- [ ] **Step 3: Empty-state prompt suggestions** tied to the selected
  repository ("What changed?", "Show likely impact", "Find tests for…") that
  prefill the composer — no canned answers, ever.
- [ ] **Step 4: Run the web and backend gates, append the handoff.**

**Acceptance**

- A real repository can be added and watched to `active` entirely through the
  UI against a live loopback backend; no fabricated progress exists in the
  codebase.

---

## P5-07 — Sidebar and Conversation Management

**Files**

- Create: `apps/web/src/features/conversations/sidebar/` (ConversationList,
  date grouping, search filter, NewChatButton, RenameDialog,
  ArchiveDeleteMenu + tests)

**Interfaces**

- Consumes: P5-02 endpoints via generated types.

**Steps**

- [ ] **Step 1: Write failing component tests**: conversations group by
  relative date from backend timestamps; search filters by title; rename
  updates optimistically and reconciles; archive hides from the default list;
  delete asks for confirmation naming the soft-delete behavior; keyboard
  navigation traverses the list; the active conversation matches the URL.
- [ ] **Step 2: Implement**, including infinite scrolling on the cursor API.
- [ ] **Step 3: Run the gates and append the handoff.**

**Acceptance**

- Creating, opening (URL-routed), renaming, archiving, and deleting all work
  against the real backend with reconciliation by ID.

---

## P5-08 — Thread View: Submit, Stream, Cancel, Retry

**Files**

- Create: `apps/web/src/features/conversations/thread/` (MessageList,
  UserTurn, AssistantTurn, StreamingStatus, Composer, RetryControls + tests)

**Interfaces**

- Consumes: P5-03 submit/retry/cancel endpoints, P5-04 stream, P5-05
  `Markdown` + SSE client.

**Steps**

- [ ] **Step 1: Write failing component tests**: optimistic user message
  reconciles by ID; streamed sections appear in order and duplicates are
  dropped; the streaming status line shows the typed retrieval stages
  ("Resolving symbols…"); cancel leaves an explicit cancelled turn; retry
  creates a new run and keeps the failed turn visible; switching threads
  mid-stream leaks nothing into the other thread; the freshness banner shows
  the run's snapshot when not current; assistant content renders through the
  sanitizer only.
- [ ] **Step 2: Implement** the thread with structured answer sections
  (summary, findings by severity, affected files, tests/docs, limitations,
  collapsible evidence list — Section 14.3), reconnect on tab refocus, and
  the composer (multiline, Enter-to-send / Shift+Enter newline, cancel
  button while running, mode selector stub for preflight).
- [ ] **Step 3: Run the gates and append the handoff.**

**Acceptance**

- Gate conditions 2 and 3 now hold end to end in the browser, verified by
  component tests here and Playwright in P5-10.

---

## P5-09 — Citations, Evidence Drawer, Change Preflight

**Files**

- Create: `apps/web/src/features/evidence/` (CitationChip, EvidenceDrawer,
  ExcerptView + tests)
- Create: `apps/web/src/features/change-analysis/` (PreflightLauncher,
  ReportView + tests)

**Interfaces**

- Consumes: `GET /v1/evidence/{id}`, message evidence rows (P5-01 fields),
  change-analysis endpoints (Phase 4), `POST /v1/change-analysis/working-tree`.

**Steps**

- [ ] **Step 1: Write failing evidence tests**: a citation chip opens the
  drawer with file path, symbol, line range, derivation, confidence, and the
  message's snapshot label; the excerpt renders as highlighted *text* with
  cited lines emphasized; a hash-drifted or missing evidence fetch shows the
  explicit invalid/stale state, never silently re-resolved content;
  keyboard: chips are buttons, drawer traps and restores focus.
- [ ] **Step 2: Implement** the drawer (right rail on desktop, overlay on
  medium, sheet on mobile).
- [ ] **Step 3: Write failing preflight tests**: the composer shortcut runs a
  working-tree preflight for the thread's repository; the report renders
  risk-ordered findings grouped by severity with citations through the same
  drawer; warnings and limitations are visible, not tucked away; a failed
  analysis shows its error code and is retryable.
- [ ] **Step 4: Implement** the preflight experience over the persisted
  Phase 4 analysis (no re-analysis on re-open — the stored report is the
  truth).
- [ ] **Step 5: Run the gates and append the handoff.**

**Acceptance**

- Every material claim in a rendered answer is clickable to hash-verified
  evidence; the drawer states derivation and snapshot explicitly.

---

## P5-10 — Settings, Accessibility, Responsive, E2E, Phase Gate

**Files**

- Create: `apps/web/src/features/settings/` (theme, accent, reduced motion,
  repository management + tests)
- Create: `apps/web/e2e/` Playwright suites + `playwright.config.ts`
- Create: `scripts/check_phase5.ps1`
- Create: `docs/operations/web-application.md`
- Modify: `docs/security/threat-model.md` (browser surface: sanitization,
  CORS, CSP, evidence links), `README.md`, `docs/plans/PLAN.md`, this plan

**Steps**

- [ ] **Step 1: Implement settings** (backed by `GET/PATCH /v1/settings`;
  no provider secrets rendered — Phase 7 concern).
- [ ] **Step 2: Accessibility pass as tests**: `vitest-axe` on every feature
  surface; keyboard-only walkthrough tests for sidebar, composer, drawer;
  focus management on dialogs; reduced-motion honored; contrast tokens
  verified.
- [ ] **Step 3: Responsive tests** at desktop/medium/mobile widths for the
  three-region collapse rules.
- [ ] **Step 4: Playwright critical workflows** against a real backend on a
  temp database: onboard → index → converse → citation → drawer;
  **restart persistence** (kill and restart the backend, reload the page,
  history intact — gate 1); cancel/reconnect mid-stream (gate 2); historical
  snapshot label after re-index (gate 3); preflight report.
- [ ] **Step 5: Write `check_phase5.ps1`** (backend gate + `pnpm lint`,
  `typecheck`, `test`, `build`, type-generation `--check`, Playwright), run
  the full gate on Windows, record commands/exit codes/results, and set
  Phase 5 to `awaiting_user_approval`.

**Acceptance**

- The gate table at the top of this plan is measured and reported, including
  any miss; `check_phase5.ps1` exits 0 on Windows.

---

## Verification Commands

```powershell
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run python scripts/export_contract_schema.py --check
powershell -ExecutionPolicy Bypass -File scripts/generate_web_types.ps1 -Check
cd apps/web; pnpm lint; pnpm typecheck; pnpm test; pnpm build
cd apps/web; pnpm exec playwright test
powershell -ExecutionPolicy Bypass -File scripts/check_phase5.ps1
```

## Open Questions for the User (resolve at plan approval)

1. **Dependency surface.** The web app introduces Node 20, pnpm, and the
   decision-5 package set — the first non-Python runtime in the repository.
   Acceptable as specified, or should any choice change (e.g., no Radix, no
   Zustand)?
2. **Soft-delete retention.** Deleted conversations are recoverable until
   Phase 6 defines retention. Is an explicit "purge now" control required in
   Phase 5 settings?
3. **`codeatlas serve --web`.** Building the static-serving command in
   Phase 5 (as planned) vs deferring all serving to Phase 6 packaging.

## Task Status Transitions

`docs/plans/PLAN.md` holds the authoritative status and the full handoff
evidence for every transition once the phase activates.
