# ADR-0006 — Persistent Web Application Design

Status: accepted
Date: 2026-07-27
Deciders: user (approved the Phase 5 plan and the Phase 4 gate on 2026-07-27)
Supersedes: none
Related: ADR-0003 (evidence granularity), ADR-0004 (contract), ADR-0005
(change assurance), `docs/plans/phases/phase-05-persistent-web-application.md`

## Context

Phase 5 adds the first user interface and the first persistent conversation
state. Two things make it different from every phase before it: it introduces
a second runtime (Node/browser) into a Python repository, and it stores data
that users will expect to keep — chat history is first-class application data
(`AGENTS.md` Section 8.2), not view state.

The risk is that a chat surface quietly becomes a second, weaker path to
repository truth: its own retrieval, its own evidence handling, its own
freshness story. The decisions below exist mostly to prevent that.

## Decision

### 1. Conversation persistence (migration `0008`, `SCHEMA_VERSION` 7 → 8)

Five additive tables: `conversations`, `messages`, `message_runs`,
`message_evidence`, `message_feedback`. Forward-only; `0001`–`0007` are never
edited.

- **Deleting a conversation is soft** (`deleted_at`), recoverable until
  Phase 6 defines retention. **Deleting a repository cascades** to its
  conversations — that is the explicit policy Section 8.2 requires, and the
  confirmation dialog states it.
- **`message_evidence` snapshots the evidence fields** (path, symbol, range,
  content hash, snapshot ID) instead of joining live index tables. A
  historical message must keep telling the truth it told after its snapshot
  is superseded. This is the same audit rule migration `0007` established for
  change analyses, and for the same reason: derived history that silently
  re-resolves is not history.
- Columns are bounded (`content` ≤ 64 KiB, warnings JSON ≤ 8 KiB). The
  repository corpus is never duplicated into chat rows.

### 2. Transactional message lifecycle

Creating a user message, its queued assistant message, and its run is **one
transaction**; completing an assistant message with its evidence rows is
**one transaction**. Failed and cancelled runs stay visible and retryable; a
retry creates a *new* run and preserves the prior one, because the audit
trail of what was attempted is part of the record.

One in-process `asyncio` worker executes runs. No broker, no second process:
this is a single-user local product (`AGENTS.md` Section 4.5), and the
synchronous `/v1/query` path is unchanged.

### 3. One pipeline, no chat-only retrieval

`AnswerPipeline` implements Section 10.1 steps 1–13 and 16–17 over the
*existing* application services. A contract test asserts that the same
question through the conversation pipeline and through `/v1/query` yields the
same claims, evidence IDs, and warnings against the same snapshot.

**No LLM and no embeddings in Phase 5.** Every assistant message is a
deterministic structured answer or an explicit abstention, rendered from
templates. Repository text is interpolated only inside code spans. Generation
is Phase 7, behind its own approval gate.

### 4. Typed SSE with a bounded replay buffer

`GET /v1/conversations/{id}/stream`, hand-rolled over FastAPI's
`StreamingResponse` — no new dependency for something this small. Events are
exactly the Section 11.2 vocabulary, each carrying `contract_version`,
`request_id`, `conversation_id`, `message_id`, a monotonically increasing
`sequence`, a UTC timestamp, and a typed payload. SSE `id:` is the sequence,
so `Last-Event-ID` resumes.

Replay is a **256-event in-memory ring buffer per active run**. Inside the
buffer a reconnect replays the missed events; outside it (or after
completion) the client fetches the final persisted message. Events are not
persisted, because **streaming text is provisional and the persisted message
is authoritative**. Persisting the stream would create a second record of the
answer that could disagree with the first.

### 5. Frontend stack

| Concern | Choice | Why |
| --- | --- | --- |
| Build | Vite + React 18 + TypeScript strict | Section 6.2 |
| Package manager | pnpm, lockfile committed | blueprint tree |
| Styling | Tailwind + CSS custom-property tokens | utility CSS; tokens carry light/dark and one accent |
| Primitives | Radix UI (dialog, dropdown, tooltip) | headless and accessible; no visual framework lock-in |
| Server state | TanStack Query | Section 6.2 |
| Routing | react-router, `/conversations/:conversationId` | the URL identifies the thread (Section 14.5) |
| Local UI state | React state + Zustand for layout only | "only where React state is insufficient" |
| API types | `openapi-typescript` → checked-in generated file with a `--check` script | Section 6.2's "generated or centrally defined"; same discipline as the contract schema export |
| Markdown | `react-markdown` + `rehype-sanitize`, strict schema, no raw HTML | Section 14.3 |
| Tests | Vitest + Testing Library + vitest-axe; Playwright for E2E | Section 6.2 |

This introduces Node 20 and pnpm as documented Windows prerequisites — the
first non-Python runtime in the repository. It is recorded here because it is
a real expansion of the dependency surface, not an implementation detail.

### 6. Six error codes (`contract_version` stays `"1.0"`)

| Code | HTTP | CLI |
| --- | --- | --- |
| `CONVERSATION_NOT_FOUND` | 404 | 3 |
| `MESSAGE_NOT_FOUND` | 404 | 3 |
| `RUN_NOT_CANCELLABLE` | 409 | 3 |
| `RUN_NOT_RETRYABLE` | 409 | 3 |
| `CONVERSATION_ARCHIVED` | 409 | 3 |
| `QUERY_TOO_LONG` | 422 | 2 |

`RUN_NOT_CANCELLABLE` is the only one marked retryable: the answer depends on
when the question is asked, since a run may finish between the client's
decision and its request.

A soft-deleted conversation reports `CONVERSATION_NOT_FOUND`. Reporting the
row because it physically survives would contradict what the user was told.

### 7. Contract models are additive and strict

`Conversation`, `Message`, `MessageRun`, `MessageEvidenceItem`,
`StreamEvent`, `ConversationPage`, `MessagePage` — all frozen with
`extra="forbid"`. Two validators encode rules the storage layer depends on: a
`complete` message must carry content (a completed answer with no text is the
silent-success failure the evidence contract exists to prevent), and a
`failed` message must carry an error code. Sequence numbers start at 1, so 0
can mean "nothing yet" to the stream.

### 8. Deterministic conversation titles

The first user message, normalized and truncated at a word boundary ≤ 60
characters. Model-generated titles are optional and non-authoritative
(Section 8.2), so they wait for Phase 7. Rename is always available.

### 9. Serving model

Development runs the Vite dev server with `/v1` proxied to the loopback API.
A production static mount ships behind `codeatlas serve --web`, but
packaging and installation remain Phase 6. The API stays bound to loopback;
CORS allows only the local dev origin.

### 10. Browser trust boundary

Repository content is untrusted in the browser exactly as it is on the
server. Rendered Markdown is sanitized with a strict schema — no raw HTML,
scripts, styles, event handlers, or `javascript:` links — and evidence
excerpts render as text in code blocks, never as markup. This is asserted by
component tests, not assumed.

## Consequences

- A second runtime, lockfile, and test stack enter the repository; the
  Windows gate script grows a frontend section.
- Conversation history becomes user data with retention consequences, which
  Phase 6's backup/restore/deletion workflow must cover.
- Because no LLM is admitted, Phase 5's answers are only as good as the
  deterministic pipeline. That is the point: the UI must expose evidence and
  uncertainty rather than paper over them with prose.
- The generated API types create a staleness failure mode; the `--check`
  script is what keeps it from becoming a silent one.

## Alternatives considered

- **WebSockets instead of SSE.** Rejected: answers stream one way, and
  Section 6.2 requires proving bidirectional need first.
- **Persisting stream events.** Rejected: it creates a second record of an
  answer that can disagree with the persisted message.
- **A browser-side database (IndexedDB) as the history store.** Rejected
  outright by Section 6.2 — the backend owns conversations.
- **Model-generated titles in Phase 5.** Deferred: it would introduce a
  provider before the semantic gate.
