# Phase 6 — Continuous Freshness and Hardening

Status: `draft` (authored 2026-07-28 after the Phase 5 gate approval; PLAN.md
rule 11 — no task may leave `pending` until the user approves this plan)
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

## Completion Gate (from `AGENTS.md` Section 20)

Phase 6 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log.

| # | Gate condition | Measured against |
| --- | --- | --- |
| 1 | The Phase 5 conditions that were deferred now pass end to end: history survives a backend restart, a stream reconnects mid-run, and the critical workflows run in a browser | Playwright suites |
| 2 | A file changed on disk is reflected in query results without an explicit index command, within a declared debounce window | watcher integration tests |
| 3 | Filesystem events alone are never treated as truth: a reconciling scan corrects missed, duplicated, and out-of-order events | watcher reconciliation tests |
| 4 | A process killed mid-index recovers to the previous active snapshot with no orphaned rows, and says what it recovered | crash-recovery tests (extending the Phase 2 suite) |
| 5 | A packaged Windows build installs, runs, and upgrades from the previous schema version without losing a snapshot or a conversation | packaging + upgrade tests |
| 6 | Backup, restore, and deletion are explicit, complete, and reversible where documented; a restored database passes integrity checks | backup/restore tests |
| 7 | Performance targets from Section 19.3 still hold on the packaged build, on named hardware | `scripts/measure_phase6_perf.py` |
| 8 | The security sweep passes against the packaged artifact, including the browser surface | `tests/security/**`, updated threat model |
| 9 | Phases 1–5 gates still pass unchanged | `check_phase5.ps1` plus the new `check_phase6.ps1` |

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
| P6-SETUP | ADR-0007, error codes, `check_phase6.ps1` skeleton | Phase 5 | `pending` |
| P6-01 | Playwright harness and the three deferred Phase 5 suites | P6-SETUP | `pending` |
| P6-02 | Filesystem watcher: debounce, subtree scan, incremental index | P6-SETUP | `pending` |
| P6-03 | Reconciliation scan and lossy-event tests | P6-02 | `pending` |
| P6-04 | Crash recovery reporting and diagnostics | P6-SETUP | `pending` |
| P6-05 | Backup, restore, deletion, and integrity validation | P6-04 | `pending` |
| P6-06 | Packaging, `serve --web`, and the install workflow | P6-01, P6-05 | `pending` |
| P6-07 | Upgrade and migration workflow from a real prior version | P6-06 | `pending` |
| P6-08 | Performance, security, Windows release validation, docs, phase gate | P6-03, P6-07 | `pending` |

## Open Questions for the User

1. **Packaging tool.** PyInstaller is assumed. If you prefer an MSI/WiX
   installer or a different bundler, that changes P6-06 substantially.
2. **Watcher default.** Should the watcher be on by default for a registered
   repository, or opt-in per repository? On-by-default is friendlier; opt-in is
   more predictable about background CPU.
3. **Retention.** Phase 5 left soft-deleted conversations recoverable forever
   with no purge control. Phase 6 should decide the policy: a purge action, a
   time-based sweep, or both.
4. **Scope of the Playwright suites.** The gate lists three. Confirm whether
   the full Section 14 workflow set is wanted now or only the deferred three.

## Verification Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase6.ps1 -SkipSync
cd apps/web; pnpm exec playwright test
uv run python scripts/measure_phase6_perf.py
```
