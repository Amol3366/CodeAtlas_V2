# ADR-0008 — Accept-Then-Stream Message Submission

Status: accepted
Date: 2026-07-28
Deciders: user (explicitly approved on 2026-07-28, per `CLAUDE.md` Section 25)
Related: ADR-0006 (web application), `CLAUDE.md` Sections 11.2, 12.2, 14.5, 25,
`docs/plans/phases/phase-06-freshness-and-hardening.md`

## Context

`POST /v1/conversations/{id}/messages` currently creates the user message,
executes the whole run inline, and returns the finished assistant answer in the
same response.

That is a **deviation from the specification, not an extension of it.**
`CLAUDE.md` Section 12.2 states: *"Prefer a single request that creates the user
message and starts its run. Return IDs immediately, then stream or poll status."*
The inline endpoint returns IDs only once the work it was supposed to start has
already finished.

The deviation was invisible until a browser exercised it. P6-01 built the
Playwright harness and found that the stream-reconnection suite **cannot** prove
what the Phase 5 gate asks of it:

- no run is ever in flight, because submission blocks until the run completes;
- `Thread` therefore never opens a stream at all;
- the suite falls back to proving the SSE transport contract directly, and says
  plainly what it does not cover.

So gate condition 1 of Phase 6 ("a stream reconnects mid-run") is unprovable
against the current contract. This is Phase 5 debt that P6-01 declared rather
than absorbed, and it was carried explicitly to a user decision because changing
the response shape of a published endpoint falls under Section 25.

Three further consequences of inline execution are worth naming, because they
are defects the current shape makes unavoidable rather than accidents:

1. **A long run holds an HTTP request open for its full duration**, at the mercy
   of any proxy or client timeout. The answer is persisted, but the client that
   asked for it may never see the response.
2. **Cancellation has nothing to cancel.** `POST /v1/message-runs/{run_id}/cancel`
   can only ever arrive after the run it names has finished.
3. **A reload mid-answer loses the stream**, because there was no stream — the
   client's only recourse is to re-fetch the finished message.

## Decision

**Replace inline execution with accept-then-stream.** The alternative shapes are
recorded under "Alternatives" below and were rejected.

### Contract

```text
POST /v1/conversations/{id}/messages
  -> 202 Accepted
     { message_id, run_id, status: "queued", contract_version, request_id }

GET  /v1/conversations/{id}/stream?after=<sequence>
  -> run.accepted, retrieval.started, retrieval.progress,
     evidence.available, generation.delta, answer.completed
     (or run.warning / run.failed / run.cancelled), heartbeat
```

The run executes in the background. The endpoint returns as soon as the user
message and its queued run are committed — which Section 8.2 already requires to
be a single transaction, so the accepted response is durable, not optimistic.

### Rules this preserves

- **The persisted message stays authoritative.** Streamed text remains
  provisional (Section 11.2). A client that misses every frame can still fetch
  the final message and be correct.
- **The existing replay buffer and `?after=` resumption are reused unchanged.**
  P6-01 already proved gapless monotonic sequences and exact resumption at the
  transport level; this change is what finally puts a real run behind them.
- **Reconnect is idempotent.** Duplicate events are ignored by sequence, per
  Section 14.5.
- **A stream opened for a run that already finished** directs the client to the
  persisted message rather than replaying a completed run — the `stream.closed`
  directive P6-01 added already covers this, and it is the reload path.
- **Cancel and retry become meaningful** rather than vestigial: cancel reaches a
  run that is actually executing, and a retry creates a new run while preserving
  the prior audit record (Section 8.2).

### Versioning

The response body of an existing endpoint changes shape, so this is a breaking
change to a published contract and is treated as one:

- a new contract schema entry is added for the accepted-submission response;
- `contract_version` moves from `"1.0"` to `"1.1"`, the first bump in six
  phases, because the alternative — reusing `"1.0"` for two incompatible shapes
  — makes the version field a lie;
- the change is recorded in the contract test suite and the exported schema,
  and the cross-adapter suite is extended so REST, CLI, and MCP agree on the new
  shape.

## Section 25 checklist

Section 25 requires five things before a breaking contract change. Recorded
explicitly so the approval is auditable:

| Requirement | Where satisfied |
| --- | --- |
| Documented user need | Phase 6 gate condition 1; the three defects above |
| Benchmark or discovery evidence | P6-01's Playwright finding — the suite that could not be written |
| Security and operational impact | Below |
| Migration and rollback plan | Below |
| Explicit approval | User, 2026-07-28 |

### Security and operational impact

- **A background run outlives its request**, so it needs the same cooperative
  cancellation, timeout, and bound enforcement the inline path had (Section
  10.3). Nothing may become unbounded merely because nobody is waiting on it.
- **Concurrency exposure grows.** P6-01 found that a shared SQLite connection
  corrupted under four concurrent page-load requests; background runs make
  concurrent database access the normal case rather than the burst case. The
  per-request connection scoping from P6-01 is a prerequisite, not an
  optimization, and the background executor must obtain its own connection
  through the same factory.
- **No new network surface.** The API stays bound to loopback; no endpoint is
  added, and the stream endpoint already exists.
- **No new content in logs.** Run lifecycle telemetry continues to carry
  outcomes and IDs, never prompts, excerpts, or answers (Section 17).

### Migration and rollback

- **Migration:** the web client is the only consumer, and it ships from this
  repository, so both sides move together. No stored data changes shape and no
  SQLite migration is required — `SCHEMA_VERSION` stays 9.
- **Rollback:** revert the commit. Because no schema or persisted record
  changes, rollback is a code-only operation with no data consequence, which is
  precisely why this change is safe to make now rather than after packaging
  (P6-06) puts a built artifact in a user's hands.

## Alternatives considered

1. **Add a parallel async endpoint, keep inline as the default.** Avoids the
   version bump and the Section 25 gate entirely. Rejected: the backend would
   carry two execution paths for one use case indefinitely, the UI must still
   pick one, and the unpicked path becomes untested weight that nonetheless has
   to keep working. Avoiding a version bump is not worth a permanent fork in the
   core request path.
2. **Decline; keep inline execution.** Rejected: it leaves gate condition 1
   permanently unprovable, and leaves cancellation as an endpoint that cannot do
   what its name says — which is exactly the kind of hollow surface Section 21
   forbids ("no placeholder production path, fake success").
3. **Poll instead of stream.** Rejected: the typed event schema in Section 11.2
   and the replay buffer already exist and are proven. Polling would add a
   second progress mechanism and still not deliver `generation.delta`.

## Consequences

- Phase 6 gate condition 1 becomes provable, and the P6-01 stream suite can be
  extended to open a stream against a live run and reconnect mid-answer.
- `Thread` gains a real streaming path, which is also where the two remaining
  Phase 5 UI gaps get closed cheaply: it currently passes `snapshotId={null}`
  so the freshness banner can never appear, and citations are not restored after
  a reload. Both are in the same component and the same task.
- The first `contract_version` bump establishes how later ones are done.
- Scheduled as **P6-STREAM**, ahead of P6-03, per the user's sequencing decision
  on 2026-07-28.
