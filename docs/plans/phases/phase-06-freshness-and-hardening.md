# Phase 6 — Continuous Freshness and Hardening

Status: `complete` — **gate approved by the user 2026-07-29**, with four
qualifications stated before approval and carried by it, the first being an
unfixed defect (the API process can crash under sustained change analysis; see
gate condition 7 and `docs/evaluation/phase-6-baseline-environment.md`). The
plan itself was approved 2026-07-28, with the stated defaults for all four open
questions; see "Resolved Defaults" below.
Gate authority: user
Prerequisites: Phase 5 approved; `AGENTS.md` Sections 9, 15, 17, 18, 19; the
blueprint

## Outcome

CodeAtlas becomes something a person can install, leave running, and trust
after a crash. A watcher keeps the index current without being told; an
interrupted or corrupted install recovers to its last valid state and says what
happened; a packaged Windows build upgrades in place without losing a snapshot
or a conversation; and the security and performance claims made in earlier
phases are re-verified on the packaged artifact rather than on a developer
checkout.

This is the phase where the product stops being a repository you run from
source.

## The Debt Phase 5 Handed Over

The Phase 5 gate was approved with three conditions only partly met, all for
one reason: **no Playwright end-to-end suites exist.** Restart persistence,
stream reconnection, and the critical-workflow coverage were proven at the
storage, backend, and component layers but never through a browser.

That gap is **P6-01**, first in the phase, not an appendix. A gap accepted at
one gate becomes a debt the next phase either pays or re-declares; paying it
first also means every later hardening task has an end-to-end harness to prove
itself against.

### What P6-01 found, and the one part it could not pay

The harness and all three suites landed, and two of the conditions are now met
in a browser. Along the way the suites exposed three defects invisible to unit
tests, the serious one being that concurrent requests corrupted the API's
shared SQLite connection — a browser makes four requests on page load, and the
result was intermittent 500s and, worse, one request reading another's result
columns. Fixed by scoping the connection to the request.

**Gate condition 1 remains partly open, and needs a user decision.** Proving a
stream reconnects *mid-run* is impossible against the current contract:
`POST /v1/conversations/{id}/messages` runs the answer inline and returns it
finished, so no run is ever in flight, and `Thread` never opens a stream at all.
Making it provable means an accept-then-stream submission contract — a breaking
API change, which Section 25 of `AGENTS.md` puts behind explicit approval. The
suite proves the transport contract instead and says plainly what it does not
cover. **This is carried as Phase 5 debt awaiting a decision, not silently
absorbed.**

**Decided 2026-07-28, and delivered.** The user approved replacing inline
execution with accept-then-stream and chose to build it before P6-03. The
decision and its Section 25 checklist are in
[ADR-0008](../../adr/0008-accept-then-stream-message-submission.md), whose
Outcome section records what implementation added to it. **P6-STREAM is
`complete` and gate condition 1 is met**: `check_phase6.ps1` passes with
Playwright included.

**The qualification, stated at the gate rather than in a footnote.** Four
conversation-route browser tests are **skipped on Chromium**, whose renderer
crashes on client-side navigation to `/conversations/{id}`. It is a browser
defect and not application code — Firefox passes all seven suites, no JS error
is raised in a production or a development React build, and the heap is flat at
the moment of death. It is unresolved upstream; a Playwright version bisect
would name the build that introduced it. Every assertion still runs, on Firefox;
what is lost is the engine four of them are proven on.

Worth stating plainly, because it changes what this task is: the inline endpoint
is a **deviation from `CLAUDE.md` Section 12.2**, which already specifies
"Return IDs immediately, then stream or poll status." P6-STREAM closes a gap
against the existing specification rather than expanding scope.

## Completion Gate (from `AGENTS.md` Section 20)

Phase 6 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log.

| # | Gate condition | Measured against |
| --- | --- | --- |
| 1 | The Phase 5 conditions that were deferred now pass end to end: history survives a backend restart, a stream reconnects mid-run, and the critical workflows run in a browser | Playwright suites — **met 2026-07-28** (P6-01 + P6-STREAM); see the Chromium qualification below |
| 2 | A file changed on disk is reflected in query results without an explicit index command, within a declared debounce window | watcher integration tests — **met 2026-07-28** (P6-02): `test_watcher_end_to_end.py::test_an_edit_on_disk_reaches_query_results_unasked` adds a method to a file on disk and waits for `lookup` to resolve it, with no `index` call. The evidence row was missing from this table until P6-08 noticed it; the test has passed since P6-02 |
| 3 | Filesystem events alone are never treated as truth: a reconciling scan corrects missed, duplicated, and out-of-order events | watcher reconciliation tests — **met 2026-07-28** (P6-03): `tests/integration/test_watch_reconciliation.py` proves each failure shape end to end, and the periodic plus startup scans run in real operation |
| 4 | A process killed mid-index recovers to the previous active snapshot with no orphaned rows, and says what it recovered | crash-recovery tests — **met 2026-07-28** (P6-04): a genuinely killed subprocess is recovered and reindexes, no snapshot-scoped table keeps rows for the dead snapshot, and diagnostics distinguish an interrupted run from a repository never indexed. Recovery also stopped being able to destroy a live index; see the ADR-0007 Outcome section |
| 5 | A packaged Windows build installs, runs, and upgrades from the previous schema version without losing a snapshot or a conversation | packaging + upgrade tests — **met 2026-07-28** (P6-06 + P6-07): the packaged binary upgrades a database written by a *real* prior build, checkpointing before it migrates, and every declared row survives. An older build opening a newer database now refuses instead of quietly serving a schema it has never seen |
| 6 | Backup, restore, and deletion are explicit, complete, and reversible where documented; a restored database passes integrity checks | backup/restore tests — **met 2026-07-28** (P6-05): a backup taken from an open database restores and answers; a corrupted or newer-schema backup is refused *before* the target is touched; repository deletion refuses to take conversations without an explicit cascade; the retention sweep never touches an undeleted conversation |
| 7 | Performance targets from Section 19.3 still hold on the packaged build, on named hardware | `scripts/measure_phase6_perf.py` — **met 2026-07-28** (P6-08): refresh p95 **1.33 s** (≤ 2 s), preflight p95 **3.09 s** (≤ 10 s), cold start 1.63 s, measured on the artifact over its own API. Both are *better* than the Phase 4 source numbers, because the measurement found and fixed unbounded snapshot accumulation. It also found an **unfixed crash**, recorded in `docs/evaluation/phase-6-baseline-environment.md` |
| 8 | The security sweep passes against the packaged artifact, including the browser surface | `tests/security/test_packaged_surface.py`, updated threat model — **met 2026-07-28** (P6-08): loopback-only binding proven on a socket, non-loopback refused, no CORS headers, the error envelope intact, traversal refused, and no developer material in the bundle. It found the SPA fallback returning a bare 404 for unknown `/v1` paths instead of the envelope |
| 9 | Phases 1–5 gates still pass unchanged | `check_phase5.ps1` plus the new `check_phase6.ps1` — **met 2026-07-28**: `check_phase0` through `check_phase5` all exit 0, as does `check_phase6 -Package` |

A missed target is reported as missed, with the measurement and the reason.

## Global Constraints

Phase 1–5 constraints all still apply. Additions and emphases:

- **The watcher is an optimization, never an authority.** A filesystem event
  triggers work; it does not *establish* that work is needed. Every conclusion
  still comes from a scan and a content hash, because event delivery is lossy,
  duplicated, and reordered on every platform — and silently on Windows when a
  buffer overflows.
- **Recovery preserves the last valid active snapshot.** No recovery path may
  leave a repository with no queryable state; that is the invariant Phase 2
  established and packaging must not weaken it.
- **A migration that can lose data must be preceded by a checkpoint.** The
  upgrade path is tested from a real prior-version database, not a synthetic
  one.
- **Packaging changes no runtime contract.** A packaged build answers exactly
  what a source checkout answers; if it cannot, the difference is a defect, not
  a packaging detail.
- **No new network surface.** The API stays loopback-bound. Packaging is not an
  occasion to expose it, and the installer requests no elevated privilege it
  does not need.
- Migrations remain forward-only and additive. `0001`–`0008` MUST NOT be
  edited.
- Exactly one task may be `in_progress` or `verifying`.
- Test-first: write the failing test, observe it fail, then implement. **This
  was not honored for the Phase 5 UI slices; it is a stated expectation here.**

## Non-Goals (explicitly deferred)

| Deferred item | Phase |
| --- | --- |
| Embeddings, reranking, any model provider | 7 |
| Multi-user, auth, tenancy, network exposure | out of MVP scope |
| Auto-update from a remote server | out of scope (no cloud dependency) |
| macOS or Linux installers | out of scope for the MVP profile |
| Background indexing of unopened repositories | out of scope |
| Telemetry upload of any kind | never without explicit opt-in |

## Phase Architecture Decisions

Fixed so tasks compose. Deviation requires an ADR and user approval. ADR-0007
(P6-SETUP) records these.

### 1. The watcher is a debounced trigger over a reconciling scan

```text
filesystem events ──▶ debounce (declared window) ──▶ scan the affected subtree
                                                  ──▶ hash compare
                                                  ──▶ incremental index
periodic reconcile ──────────────────────────────────▶ full scan compare
```

Events name *candidates*. The scan decides. A periodic reconciliation catches
what the event stream dropped, which is the only defense against a silently
overflowed watch buffer.

### 2. Recovery is idempotent and self-describing

Startup recovery already exists (Phase 2). Phase 6 extends it to report what it
did: a repository whose last index was interrupted says so in its diagnostics
rather than looking indistinguishable from one that was never indexed.

### 3. Packaging: PyInstaller plus the built web assets

One executable that serves the API on loopback and the built SPA from
`StaticFiles`, launched by a single command. `codeatlas serve --web` — deferred
in Phase 5 and therefore still unbuilt — lands here, because packaging is what
makes it meaningful.

### 4. Backup is a checkpointed copy, not a file copy

SQLite in WAL mode cannot be safely copied while open. Backup uses the online
backup API; restore validates schema version and integrity before replacing
anything, and refuses rather than half-restoring.

## Task Board

| Task | Deliverable | Dependencies | Status |
| --- | --- | --- | --- |
| P6-SETUP | ADR-0007, error codes, `check_phase6.ps1` skeleton | Phase 5 | `complete` |
| P6-01 | Playwright harness and the three deferred Phase 5 suites | P6-SETUP | `complete` |
| P6-02 | Filesystem watcher: debounce, subtree scan, incremental index | P6-SETUP | `complete` |
| P6-STREAM | Accept-then-stream submission (ADR-0008), `contract_version` 1.1, live-run reconnect suite | P6-01 | `complete` |
| P6-03 | Reconciliation scan and lossy-event tests | P6-02 | `complete` |
| P6-04 | Crash recovery reporting and diagnostics | P6-SETUP | `complete` |
| P6-05 | Backup, restore, deletion, and integrity validation | P6-04 | `complete` |
| P6-06 | Packaging, `serve --web`, and the install workflow | P6-01, P6-05 | `complete` |
| P6-07 | Upgrade and migration workflow from a real prior version | P6-06 | `complete` |
| P6-08 | Performance, security, Windows release validation, docs, phase gate | P6-03, P6-07 | `complete` |

**P6-STREAM was inserted on 2026-07-28**, after the user approved the
accept-then-stream contract change (ADR-0008) and chose to build it before
P6-03. It is placed here rather than appended because it pays the Phase 5 debt
that P6-01 could only declare, and because every later suite is stronger once
the stream contract behind it is real.

**P6-03 returned to `ready` when P6-STREAM completed**, as planned. It was
`pending` only to record the user's sequencing decision, never because anything
blocked it — which kept the "Dependencies" column meaning what it says instead
of absorbing an ordering preference.

### P6-STREAM acceptance criteria

1. `POST /v1/conversations/{id}/messages` returns `202` with `message_id`,
   `run_id`, and `status: "queued"` once the message and queued run are
   committed; the run executes in the background.
2. The background executor obtains its own connection through the injected
   factory (the P6-01 rule), and honours the existing timeout, bound, and
   cooperative-cancellation contracts (Section 10.3).
3. `contract_version` becomes `"1.1"`; the exported schema is regenerated and
   `export_contract_schema.py --check` passes; contract and cross-adapter
   suites are extended so REST, CLI, and MCP agree on the new shape.
4. `Thread` submits, opens the stream, renders `generation.delta`, and resumes
   at the last sequence after a reload; duplicate events are ignored.
5. `POST /v1/message-runs/{run_id}/cancel` reaches a run that is actually
   executing, and the cancelled run stays visible and retryable.
6. The Playwright stream suite is extended to reconnect **mid-run** against a
   live run, which is what makes gate condition 1 provable.
7. `Thread` stops passing `snapshotId={null}` so the freshness banner can
   appear, and citations are restored after a reload — the two Phase 5 UI gaps
   that live in the same component.
8. Test-first: each behavior above starts from a test observed failing.

## Resolved Defaults

The user approved this plan on 2026-07-28 accepting the defaults. Each is
recorded with the reasoning, because a default chosen by silence is the kind
that gets re-litigated later.

1. **Packaging: PyInstaller.** A single executable serving the API on loopback
   and the built SPA from `StaticFiles`. Chosen because it needs no installer
   framework and no elevated privilege — an MSI would add both for a
   single-user local tool that writes only to its own data directory. Revisit
   if per-machine installation is ever required.
2. **Watcher: on by default, with a per-repository off switch.** The product's
   third question is "how current is that evidence?"; a watcher that is off
   until asked answers it with "stale, and you were not told". The debounce and
   reconciliation design is what bounds the cost, so the friendlier default is
   also the affordable one. A repository can disable it individually.
3. **Retention: both a purge action and a time-based sweep**, the sweep
   defaulting to **30 days** after deletion. An explicit purge lets a user act
   now; the sweep means an unattended install does not accumulate deleted
   conversations forever. Neither touches an undeleted conversation.
4. **Playwright: the three deferred suites only** — restart persistence,
   stream reconnection, and the critical onboard-to-citation workflow. The
   wider Section 14 set is worth having but is not the debt Phase 5 incurred,
   and P6-08 can propose it once the harness exists.

## Verification Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase6.ps1 -SkipSync
cd apps/web; pnpm exec playwright test
uv run python scripts/measure_phase6_perf.py
```
