# Phase 0 — Product Contract and Evaluation

Status: `complete`
Gate authority: user
Prerequisites: `AGENTS.md` and the industry blueprint

## Outcome

Create the versioned contracts, fixture corpus, deterministic evaluation
framework, security/governance documents, and reproducible baseline needed to
measure later CodeAtlas phases without an LLM.

## Global Constraints

- Python 3.12 is the target runtime.
- Core evaluation is local, deterministic, and model-independent.
- Repository fixtures are data and MUST NOT be executed, imported, built, or
  installed.
- Paths in contracts and fixtures are normalized repository-relative paths.
- Every material factual claim requires snapshot-bound evidence.
- No embeddings, LLM, MCP implementation, browser UI, cloud service, or
  repository-code execution belongs in Phase 0.
- Exactly one task may be active.

## Task Board

| Task     | Deliverable                                    | Dependencies | Status                     |
| -------- | ---------------------------------------------- | ------------ | -------------------------- |
| P0-SETUP | Shared plan control plane                      | None         | `complete`               |
| P0-01    | Python foundation and contract v1              | P0-SETUP     | `complete`               |
| P0-02    | Fixture repositories and gold cases            | P0-01        | `complete`               |
| P0-03    | Deterministic evaluation runner                | P0-02        | `complete`               |
| P0-04    | Threat model, ADR workflow, developer commands | P0-03        | `complete`               |
| P0-05    | Baseline, verification, phase-gate handoff     | P0-04        | `complete`               |

## P0-SETUP — Shared Plan Control Plane

Produces:

- the canonical phase index and handoff log;
- the sequential status and recovery protocol;
- the pointer from `AGENTS.md` to the live plan.

Acceptance:

- every agent can discover the active task from `AGENTS.md`;
- exactly one task is active;
- interruption, blocking, verification, and user gate rules are explicit.

## P0-01 — Python Foundation and Contract v1

Create the pinned `uv` project, lockfile, package structure, and test tooling.
Define strict typed models for:

- opaque identifiers and UTC timestamps;
- normalized symbol and relation types;
- controlled derivation and independent confidence;
- snapshot references, evidence, claims, findings, query responses, and errors;
- contract version literal `1.0`.

Validation must reject unknown fields, empty opaque IDs, invalid confidence,
invalid or reversed line ranges, invalid evidence, cross-snapshot evidence, and
material claims without evidence.

Tests are written and observed failing before production contract code.

## P0-02 — Fixture Repositories and Gold Cases

Create six small fixture groups:

1. Python;
2. TypeScript and JavaScript;
3. Markdown, JSON, YAML, and TOML;
4. mixed-language relationships;
5. Git changes, renames, and deletions;
6. malicious paths/content and unsupported syntax.

Create exactly 40 deterministic query cases and 24 representative change cases.
Each case declares expected symbols, relations, evidence, changes, warnings,
limitations, impact paths, and forbidden claims. A validator must confirm all
referenced files and bounded line ranges against fixture contents without
executing repository code.

## P0-03 — Deterministic Evaluation Runner

Implement versioned JSON input/output and stable Markdown reporting for:

- exact symbol resolution;
- Recall@K, MRR, and nDCG;
- primary evidence recall and validity;
- relation-path correctness;
- changed-symbol precision and recall;
- direct-impact recall;
- unsupported-claim rate and abstention correctness.

Commands support dataset validation, an honest null baseline, and later
evaluation with optional target enforcement. Invalid input, unmet enforced
targets, and internal failure use distinct nonzero exit codes.

Forbidden-claim matching uses Unicode NFC, whitespace collapse, and case
folding. Negative tests cover malformed manifests, invented paths, invalid
lines, stale snapshots, unsupported claims, and invalid evidence.

## P0-04 — Governance, Security, and Developer Workflow

Document:

- local-first and provider opt-in boundaries;
- path traversal, symlink/junction escape, malicious content, secret leakage,
  unsafe execution, redacted logging, and loopback-only exposure;
- ADR creation and approval rules;
- modular-monolith, SQLite, deterministic-first, and optional-provider choices.

Add reproducible Windows-first commands for setup, tests, linting, type checks,
dataset validation, and evaluation.

## P0-05 — Baseline and Phase Gate

Run and record the complete quality suite and environment details. The initial
product engine is explicitly `not_implemented`; product metrics are zero or not
applicable rather than invented.

The phase may enter `awaiting_user_approval` only when:

- all contracts and datasets validate;
- exactly 40 query and 24 change cases exist;
- forbidden claims and invalid evidence are exercised by negative tests;
- results are deterministic and reproducible;
- non-goals and the no-LLM evaluation truth contract are recorded;
- all required verification commands pass in the current environment.

## Phase Handoff Log

### 2026-07-25T18:14:04Z — Phase 0 approved and closed

- Agent: Codex `/root`
- Transition: P0-05 `awaiting_user_approval -> complete`; Phase 0
  `awaiting_user_approval -> complete`.
- Approval: User approved Phase 0 and explicitly instructed agents not to
  prepare Phase 1 yet.
- Verification: Status-only gate update. No executable tests were run for this
  documentation change; the current release-gate evidence remains the frozen
  full gate from 2026-07-25T16:16:02Z.
- Limitation: Git state remains unavailable in this workspace.
- Next: Wait for further user instruction before preparing Phase 1.

### 2026-07-25T16:16:02Z — P0-05 awaiting user approval

- Agent: Codex `/root`
- Transition: P0-05 `verifying -> awaiting_user_approval`.
- Verification: Frozen full gate exited 0; 50 tests passed; Ruff, strict MyPy,
  schema freshness, 6/40/24 dataset validation, and non-mutating tracked
  baseline comparison passed.
- Review: Snapshot membership, evidence-linked findings, junction containment,
  UTC types, negative cases, Windows paths, metric aggregation, and baseline
  immutability findings were addressed and regression-tested.
- Limitation: Product targets remain honestly unmet because the engine is
  `not_implemented`; Git evidence is unavailable.
- Next: Wait for explicit user approval before completing Phase 0 or planning
  Phase 1.

### 2026-07-25T15:57:24Z — P0-04 completed; P0-05 started

- Agent: Codex `/root`
- Transition: P0-04 `verifying -> complete`; P0-05
  `ready -> in_progress`.
- Verification: Frozen Windows setup and full Phase 0 script exited 0; 39 tests,
  Ruff, MyPy, schema, dataset, and null-baseline gates passed.
- Limitation: Use the documented execution-policy bypass to run local scripts.
- Next: Record tracked baseline artifacts and the final user gate.

### 2026-07-25T15:53:04Z — P0-03 completed; P0-04 started

- Agent: Codex `/root`
- Transition: P0-03 `verifying -> complete`; P0-04
  `ready -> in_progress`.
- Verification: 38 tests passed; Ruff and MyPy passed; CLI validation and null
  baseline exited 0 with deterministic outputs.
- Limitation: Product engine metrics remain zero/not applicable by design.
- Next: Add security, ADR, and Windows workflow artifacts.

### 2026-07-25T15:46:23Z — P0-02 completed; P0-03 started

- Agent: Codex `/root`
- Transition: P0-02 `verifying -> complete`; P0-03
  `ready -> in_progress`.
- Verification: 25 tests passed; Ruff and MyPy passed; six fixtures, 40 query
  cases, and 24 change cases validated without executing fixture code.
- Limitation: Change truth is declarative until the Git adapter phase.
- Next: Write failing evaluator metric and CLI tests.

### 2026-07-25T15:39:46Z — P0-01 completed; P0-02 started

- Agent: Codex `/root`
- Transition: P0-01 `verifying -> complete`; P0-02
  `ready -> in_progress`.
- Verification: 19 contract tests passed; Ruff and MyPy passed; deterministic
  contract schema exported.
- Limitation: Git state is unavailable; product engine is not implemented.
- Next: Add fixture repositories and gold cases with validator tests first.

### 2026-07-25T15:33:03Z — P0-SETUP completed; P0-01 started

- Agent: Codex `/root`
- Transition: P0-SETUP `verifying -> complete`; P0-01
  `ready -> in_progress`.
- Verification: PowerShell structural check exited 0.
- Limitation: Git state is unavailable in this workspace.
- Next: Write failing contract tests for P0-01.

### 2026-07-25T15:15:00Z — P0-SETUP started

- Agent: Codex `/root`
- Transition: `ready -> in_progress`
- Verification: Pending.
- Limitation: Git state is unavailable in this workspace.
- Next: Complete P0-SETUP, then set P0-01 to `ready`.
