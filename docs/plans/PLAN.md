# CodeAtlas Shared Execution Plan

Status: active  
Plan contract version: 1.0  
Policy authority: `CLAUDE.md`  
Blueprint: `CODEATLAS_INDUSTRY_BLUEPRINT_2026.md`

## Rules for Every Coding Agent

1. Read `CLAUDE.md`, this file, and the active phase plan before acting.
2. Inspect the workspace, available Git state, and the latest handoff.
3. Work only on the single task marked `ready`, `in_progress`, or `verifying`.
4. Do not start a task until every declared dependency is `complete`.
5. Change `ready` to `in_progress` before implementation and record the agent
   label, UTC timestamp, and observed workspace state.
6. Use test-first development for executable behavior.
7. Before completion, run the task's current verification commands and record
   the commands, exit codes, and results.
8. Append handoffs. Never rewrite or delete earlier handoff evidence.
9. Recover interrupted work in place: inspect and preserve existing work, append
   a recovery handoff, and continue the same task.
10. Only the user may approve a phase gate. An agent records the approval and
    then activates the next phase.
11. A phase plan is itself subject to user approval. A task in a phase whose
    plan has not been approved stays `ready` and MUST NOT move to `in_progress`.

## Status Model

`pending -> ready -> in_progress -> verifying -> awaiting_user_approval -> complete`

`blocked` may be entered from `ready`, `in_progress`, or `verifying`. A blocked
entry must name the failed gate, checks attempted, and the decision or authority
needed. Exactly one task may be `in_progress` or `verifying`.

## Phase Index

| Phase | Plan | Status | Gate authority |
| --- | --- | --- | --- |
| 0 — Product contract and evaluation | [phase plan](phases/phase-00-product-contract-evaluation.md) | `complete` | User |
| 1 — Repository truth vertical slice | [phase plan](phases/phase-01-repository-truth-vertical-slice.md) | `ready` | User |
| 2 — Snapshots, stable chunks, lexical retrieval | Created after Phase 1 approval | `pending` | User |
| 3 — Polyglot graph and delivery contracts | Created after Phase 2 approval | `pending` | User |
| 4 — Change assurance | Created after Phase 3 approval | `pending` | User |
| 5 — Persistent web application | Created after Phase 4 approval | `pending` | User |
| 6 — Continuous freshness and hardening | Created after Phase 5 approval | `pending` | User |
| 7 — Measured semantic uplift | Created only after its additional approval gate | `pending` | User |

## Active Work

| Field | Value |
| --- | --- |
| Active phase | [Phase 1 — Repository truth vertical slice](phases/phase-01-repository-truth-vertical-slice.md) |
| Active task | P1-SETUP — Phase activation, dependencies, ADR-0002, tooling |
| Task status | `ready` |
| Agent | Unassigned |
| Started UTC | Not started |
| Git state | Repository initialized on branch `main` with no commits yet; all files untracked. Commit/diff evidence becomes recordable after the first commit. |
| Next gate | User approval of the Phase 1 plan. Until that is recorded here, P1-SETUP stays `ready` and no Phase 1 implementation may begin. |

### Phase 1 Task Board (authoritative status)

| Task     | Deliverable                                          | Dependencies        | Status    |
| -------- | ---------------------------------------------------- | ------------------- | --------- |
| P1-SETUP | Phase activation, dependencies, ADR-0002, tooling     | Phase 0             | `ready`   |
| P1-01    | Path safety and repository identity domain            | P1-SETUP            | `pending` |
| P1-02    | Ignore rules, classification, limits, scanner         | P1-01               | `pending` |
| P1-03    | Git state adapter                                     | P1-01               | `pending` |
| P1-04    | SQLite connection, migrations, stores                 | P1-01               | `pending` |
| P1-05    | Parser registry and Python parser                     | P1-02               | `pending` |
| P1-06    | Indexing service, validation, atomic activation       | P1-03, P1-04, P1-05 | `pending` |
| P1-07    | Exact symbol lookup, status, and diagnostics services | P1-06               | `pending` |
| P1-08    | `/v1` REST adapter                                    | P1-07               | `pending` |
| P1-09    | Minimal CLI adapter                                   | P1-07               | `pending` |
| P1-10    | Security/Windows sweep, baseline, docs, phase gate    | P1-08, P1-09        | `pending` |

Task requirements, interfaces, tests, and acceptance criteria live in the
[Phase 1 plan](phases/phase-01-repository-truth-vertical-slice.md).

## Handoff Schema

Every handoff entry contains:

- UTC timestamp and agent label;
- task ID and old/new status;
- outcome and user-visible behavior;
- files created or changed;
- public contracts, migrations, or compatibility effects;
- exact verification commands, exit codes, and summarized results;
- blockers, limitations, and recovery notes;
- exact next task or required decision.

## Handoff Log

### 2026-07-25T18:37:04Z — Phase 1 plan prepared; awaiting user approval

- Agent: Claude Code `claude-opus-5`
- Transition: Phase 1 `pending -> ready`; P1-SETUP created with status `ready`.
  No task moved to `in_progress`; no Phase 1 implementation was started.
- Outcome: Created the Phase 1 shared execution plan
  (`docs/plans/phases/phase-01-repository-truth-vertical-slice.md`) covering the
  eleven Phase 1 tasks, the fixed module map, the identity scheme, the snapshot
  lifecycle, stable error codes with HTTP and CLI mappings, evidence and
  derivation rules, and per-task test-first steps with exact verification
  commands. Pointed this file's Phase 1 row and Active Work block at that plan.
- Files: `docs/plans/phases/phase-01-repository-truth-vertical-slice.md` (new);
  `docs/plans/PLAN.md` (phase index, active work, Phase 1 task board, rule 11,
  policy-authority correction).
- Contracts/migrations: None. Contract `1.0` is reused unchanged. The Phase 1
  SQLite schema is specified in the phase plan but not created.
- Correction: `AGENTS.md` was renamed to `CLAUDE.md` by the user, so this file's
  header and rule 1 now reference `CLAUDE.md` as the policy authority. Earlier
  handoffs that cite `AGENTS.md` refer to the same document under its former
  name and are left unmodified.
- Verification: Documentation-only change; no executable tests were run. The
  current release-gate evidence remains the Phase 0 entry of
  2026-07-25T16:16:02Z. Environment facts observed while planning:
  `git version 2.55.0.windows.3`, `uv 0.11.24`, Python pinned to 3.12.
- Git state: `git rev-parse --is-inside-work-tree` returns `true` on branch
  `main`, but the repository has no commits yet and every tracked path is still
  untracked, so this entry has no commit SHA. Phase 0 handoffs recorded Git as
  unavailable; that is superseded from this entry onward.
- Limitations: No commit or diff evidence can be recorded until the first
  commit exists. Dependency versions cited in the plan are the latest published
  on 2026-07-25 and must be re-resolved and locked by P1-SETUP.
- Next: User approves or amends the Phase 1 plan. On approval, an agent records
  the approval here and moves P1-SETUP from `ready` to `in_progress`.

### 2026-07-25T18:14:04Z — Phase 0 approved and closed

- Agent: Codex `/root`
- Transition: P0-05 `awaiting_user_approval -> complete`; Phase 0
  `awaiting_user_approval -> complete`.
- Approval: User approved Phase 0 and explicitly instructed agents not to
  prepare Phase 1 yet.
- Outcome: Recorded the gate approval only. Phase 1 remains `pending`; no Phase
  1 plan, activation, implementation, or preparatory changes were started.
- Files: `AGENTS.md`, `docs/plans/PLAN.md`, and
  `docs/plans/phases/phase-00-product-contract-evaluation.md`.
- Verification: Documentation/status-only gate update; no executable tests were
  run. The Phase 0 release gate remains the 2026-07-25T16:16:02Z verification
  entry.
- Limitations: Git state is unavailable because this workspace is not a Git
  repository.
- Next: Wait for further user instruction before preparing Phase 1.

### 2026-07-25T16:16:02Z — P0-05 awaiting user approval

- Agent: Codex `/root`
- Transition: P0-05 `verifying -> awaiting_user_approval`; Phase 0 remains
  incomplete until explicit user approval.
- Outcome: Recorded the honest null baseline, environment, method, artifact
  hashes, accepted non-goals, independent review, review fixes, and final gate.
- Review fixes: Added per-evidence snapshot IDs and explicit fixture snapshot
  membership; separated Git base/target evidence; linked predicted findings to
  evidence; required applicable evidence targets; contained manifest paths;
  tested a real Windows junction escape; added strict UTC stream metadata;
  added malformed/stale negative cases; hardened Windows paths; deduplicated
  rankings; excluded empty expectations from aggregates; and changed baseline
  verification from overwrite to byte comparison.
- Contracts/migrations: Contract/schema 1.0 expanded compatibly; evaluation
  dataset/prediction contracts remain 1.0; no storage migration.
- Verification: `powershell -ExecutionPolicy Bypass -File
  scripts/check_phase0.ps1` exited 0 after frozen sync; 50 tests passed in
  0.90 seconds on the final handoff state; Ruff passed; strict MyPy passed for 14 source files; dataset
  validation reported 6 fixtures, 40 queries, and 24 changes; schema and tracked
  null baseline matched; total gate wall time 6,485 ms.
- Artifacts: Baseline JSON SHA-256
  `E425A4F116AAA07036B11E0D4017BE3F7C11B4F0FA3D9148922FF65C5FA2002F`;
  Markdown SHA-256
  `F6D09C468AA04A44FE40B999CD2CE67ABF06C0E7E2C1422823F9DC06685C9A0C`;
  contract schema SHA-256
  `E78C2788CCCACCA052455FFD0EE9A592F55256CAD8C7BE827936D929297743208`.
- Limitations: Git commit/diff evidence is unavailable. The product engine is
  intentionally not implemented, so product targets are honestly unmet.
- Next: User reviews Phase 0. On approval, record it and create the
  implementation-ready Phase 1 plan from the actual tree.

### 2026-07-25T15:57:24Z — P0-04 completed; P0-05 started

- Agent: Codex `/root`
- Transition: P0-04 `verifying -> complete`; P0-05
  `ready -> in_progress`.
- Outcome: Added the local MVP threat model, provider opt-in boundary, ADR
  process and ADR-0001, Windows setup/operations documentation, frozen setup
  script, and a fail-fast Phase 0 quality script.
- Files: `docs/security/threat-model.md`, `docs/adr/`,
  `docs/operations/development-windows.md`, `scripts/setup_windows.ps1`, and
  `scripts/check_phase0.ps1`.
- Contracts/migrations: Security and architecture baseline; no migration.
- Verification: Windows setup checked 17 locked packages and exited 0;
  `check_phase0.ps1` exited 0 with 39 tests passed, Ruff clean, MyPy clean,
  dataset 6/40/24 valid, schema current, and null baseline generated.
- Limitations: PowerShell execution policy requires the documented
  `-ExecutionPolicy Bypass -File` invocation.
- Next: Generate tracked baseline artifacts and complete the Phase 0 gate
  handoff.

### 2026-07-25T15:53:04Z — P0-03 completed; P0-04 started

- Agent: Codex `/root`
- Transition: P0-03 `verifying -> complete`; P0-04
  `ready -> in_progress`.
- Outcome: Implemented deterministic dataset validation, ranked retrieval,
  evidence, relation, change, finding, forbidden-claim, abstention, and timing
  metrics; versioned predictions/reports; JSON/Markdown rendering; honest null
  baseline; and stable CLI exit codes.
- Files: `src/codeatlas/evaluation/runner.py`,
  `src/codeatlas/evaluation/cli.py`, `scripts/run_evaluation.py`, and evaluator
  tests.
- Contracts/migrations: Prediction/report contract 1.0; no migration.
- Verification: `uv run pytest -q` — 38 passed; Ruff passed; MyPy reported no
  issues in 14 source files; validate command reported six fixtures, 40 queries,
  and 24 changes; null baseline exited 0 and reported unmet product targets.
- Limitations: Product metrics are intentionally zero/not applicable until the
  engine exists.
- Next: Complete P0-04 governance, security, and Windows developer workflow.

### 2026-07-25T15:46:23Z — P0-02 completed; P0-03 started

- Agent: Codex `/root`
- Transition: P0-02 `verifying -> complete`; P0-03
  `ready -> in_progress`.
- Outcome: Added six data-only fixture groups, 40 query cases, 24 change cases,
  strict dataset models, canonical path enforcement, real line-range
  validation, unique-ID/count gates, and non-execution coverage.
- Files: `src/codeatlas/evaluation/dataset.py`,
  `tests/evaluation/test_dataset.py`, and `tests/evaluation/cases/`.
- Contracts/migrations: Evaluation dataset contract 1.0; no migration.
- Verification: `uv run pytest tests/contract
  tests/evaluation/test_dataset.py -q` — 25 passed; Ruff passed; MyPy reported
  no issues in nine source files.
- Limitations: Git changes are declarative fixture truth until a later Git
  adapter exists.
- Next: Implement P0-03 metrics and command behavior test-first.

### 2026-07-25T15:39:46Z — P0-01 completed; P0-02 started

- Agent: Codex `/root`
- Transition: P0-01 `verifying -> complete`; P0-02
  `ready -> in_progress`.
- Outcome: Established the Python 3.12 `uv` project and strict contract v1
  models for evidence, claims, findings, snapshots, query responses, errors,
  symbol/relation enums, derivation, confidence, and validation state.
- Files: `pyproject.toml`, `uv.lock`, `src/codeatlas/contracts.py`,
  `src/codeatlas/schema_export.py`, contract tests, schema export script, and
  `docs/api/contract-v1.schema.json`.
- Contracts/migrations: Public contract and schema version 1.0; no migration.
- Verification: `uv run pytest tests/contract -q` — 19 passed;
  `uv run ruff check src tests/contract scripts/export_contract_schema.py` —
  passed; `uv run mypy --no-incremental ...` — no issues in six source files.
  Generated schema SHA-256:
  `FA80D17B7F901DB74CCD43D0D3A6DC5A7A534CA60A95FA22D9AE83BE144D4F78`.
- Limitations: No Git commit evidence; product engine remains unimplemented.
- Next: Build and validate exactly 40 query and 24 change cases.

### 2026-07-25T15:33:03Z — P0-SETUP completed; P0-01 started

- Agent: Codex `/root`
- Transition: P0-SETUP `verifying -> complete`; P0-01
  `ready -> in_progress`.
- Outcome: Added the canonical index, active phase plan, status model, recovery
  protocol, handoff schema, and `AGENTS.md` discovery pointer.
- Files: `AGENTS.md`, `docs/plans/PLAN.md`, and
  `docs/plans/phases/phase-00-product-contract-evaluation.md`.
- Contracts/migrations: Plan contract version 1.0; no product or storage change.
- Verification: PowerShell structural check exited 0; the AGENTS pointer,
  canonical active task, and recorded Git limitation were present.
- Limitations: Git remains unavailable.
- Next: Implement P0-01 with contract tests first.

### 2026-07-25T15:15:00Z — P0-SETUP started

- Agent: Codex `/root`
- Transition: `ready -> in_progress`
- Outcome: Began creation of the repository-local, agent-neutral coordination
  control plane approved by the user.
- Workspace: `AGENTS.md` and the industry blueprint were present; Git metadata,
  implementation code, tests, and project configuration were absent.
- Contracts/migrations: Plan contract version 1.0; no product contract or
  database migration yet.
- Verification: Pending documentation review.
- Limitation: No commit or branch evidence can be recorded without Git metadata.
- Next: Finish P0-SETUP and activate P0-01.
