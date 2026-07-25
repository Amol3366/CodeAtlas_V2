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
| 1 — Repository truth vertical slice | [phase plan](phases/phase-01-repository-truth-vertical-slice.md) | `complete` | User |
| 2 — Snapshots, stable chunks, lexical retrieval | Created after Phase 1 approval | `pending` | User |
| 3 — Polyglot graph and delivery contracts | Created after Phase 2 approval | `pending` | User |
| 4 — Change assurance | Created after Phase 3 approval | `pending` | User |
| 5 — Persistent web application | Created after Phase 4 approval | `pending` | User |
| 6 — Continuous freshness and hardening | Created after Phase 5 approval | `pending` | User |
| 7 — Measured semantic uplift | Created only after its additional approval gate | `pending` | User |

## Active Work

| Field | Value |
| --- | --- |
| Active phase | None; Phase 1 complete, Phase 2 not activated |
| Active task | None |
| Task status | `complete` |
| Agent | Claude Code `claude-opus-5` |
| Started UTC | 2026-07-25T19:51:52Z |
| Git state | Branch `main` at `fb14126` ("initial commit", created during this session). All Phase 1 work is uncommitted on top of it. |
| Next gate | Phase 1 was approved by the user on 2026-07-25T20:04:24Z. Await user instruction before preparing or activating Phase 2. |

### Phase 1 Task Board (authoritative status)

| Task     | Deliverable                                          | Dependencies        | Status    |
| -------- | ---------------------------------------------------- | ------------------- | --------- |
| P1-SETUP | Phase activation, dependencies, ADR-0002, tooling     | Phase 0             | `complete` |
| P1-01    | Path safety and repository identity domain            | P1-SETUP            | `complete` |
| P1-02    | Ignore rules, classification, limits, scanner         | P1-01               | `complete` |
| P1-03    | Git state adapter                                     | P1-01               | `complete` |
| P1-04    | SQLite connection, migrations, stores                 | P1-01               | `complete` |
| P1-05    | Parser registry and Python parser                     | P1-02               | `complete` |
| P1-06    | Indexing service, validation, atomic activation       | P1-03, P1-04, P1-05 | `complete` |
| P1-07    | Exact symbol lookup, status, and diagnostics services | P1-06               | `complete` |
| P1-08    | `/v1` REST adapter                                    | P1-07               | `complete` |
| P1-09    | Minimal CLI adapter                                   | P1-07               | `complete` |
| P1-10    | Security/Windows sweep, baseline, docs, phase gate    | P1-08, P1-09        | `complete` |

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

### 2026-07-25T20:04:24Z — Phase 1 approved and closed

- Agent: Claude Code `claude-opus-5`
- Approval: The user reviewed the Phase 1 gate evidence, approved the phase, and
  instructed that the work be committed.
- Transition: P1-10 `awaiting_user_approval -> complete`; Phase 1
  `awaiting_user_approval -> complete`.
- Outcome: Recorded the gate approval and committed the Phase 1 vertical slice.
  Phase 2 remains `pending`; no Phase 2 plan exists and none may be started
  without a further instruction from the user.
- Files: `docs/plans/PLAN.md`,
  `docs/plans/phases/phase-01-repository-truth-vertical-slice.md`, and the
  Phase 1 progress tracker in `CLAUDE.md`.
- Contracts/migrations: None. This entry records status only.
- Verification: Status-only documentation change; no executable tests were run
  for it. The Phase 1 release-gate evidence remains the 2026-07-25T19:59:34Z
  entry, whose `scripts/check_phase1.ps1 -SkipSync` run exited 0 with 266 tests
  passed, Ruff clean, strict MyPy clean on 74 source files, dataset 6/40/24
  valid, and both tracked baselines unchanged.
- Carried-forward limitations, unchanged by this approval: one query intent
  (`exact_symbol`); no relations, additional languages, change analysis, UI, or
  provider; synchronous full-rebuild indexing without progress or cancellation;
  UNC roots rejected; a Git subdirectory indexes without Git state; and the
  `q009` evidence-granularity disagreement still awaits a product decision.
- Next: await user instruction before preparing the Phase 2 plan.

### 2026-07-25T19:59:34Z — P1-10 completed; Phase 1 awaiting user approval

- Agent: Claude Code `claude-opus-5`
- Transition: P1-10 `in_progress -> awaiting_user_approval`; Phase 1
  `in_progress -> awaiting_user_approval`. Phase 1 is **not** complete: only the
  user may approve the gate.
- Outcome: Completed the Windows and security sweep, wired the real engine into
  the Phase 0 evaluation runner, produced the first honest engine baseline, added
  the Phase 1 gate script, and refreshed the documentation.
- Files: `tests/security/test_windows_paths.py`,
  `src/codeatlas/evaluation/engine_adapter.py`,
  `tests/evaluation/test_engine_adapter.py`, `scripts/run_phase1_baseline.py`,
  `scripts/check_phase1.ps1`, `docs/evaluation/baseline-phase-1.json`,
  `docs/evaluation/baseline-phase-1.md`,
  `docs/evaluation/phase-1-baseline-environment.md`,
  `docs/operations/development-windows-phase1.md`,
  `docs/security/threat-model.md` (Phase 1 enforcement status), `README.md`.
- Contracts/migrations: No contract or schema change in this task. Schema
  version remains 1; contract version remains 1.0.

#### Completion gate evidence

Every `CLAUDE.md` Section 20 Phase 1 checklist item, with where it is proven:

1. Windows-safe registration and scanning — `test_path_safety.py`,
   `test_windows_paths.py`, `test_scanner.py`.
2. Ignore rules, classification, limits, Git-state capture —
   `test_ignore_rules.py`, `test_classification.py`, `test_scanner.py`,
   `test_git_state.py`, including a directory that is not a Git repository.
3. SQLite migrations and repository/snapshot/file models — `test_migrations.py`,
   `test_stores.py`, applied by an explicit numbered migration runner per
   ADR-0002.
4. Python symbol extraction through Tree-sitter plus `ast` —
   `test_python_parser.py`; both layers run for every file.
5. Exact symbol lookup with validated file-and-line evidence — `test_lookup.py`,
   `test_query_response_contract.py`.
6. Repository/index status API and minimal CLI — `test_rest_api.py`,
   `test_cli_workflow.py`, both over the same `ApplicationServices`.
7. Unit, integration, contract, security, and Windows-path tests — 266 tests
   across `tests/unit`, `tests/integration`, `tests/contract`, `tests/security`,
   `tests/end_to_end`, and `tests/evaluation`.
8. Same answer through all three surfaces —
   `test_cli_and_rest_return_the_same_evidence_for_the_same_snapshot` asserts an
   identical snapshot ID, evidence ID, file path, and line range.

#### Verification in the current environment

- `powershell -ExecutionPolicy Bypass -File scripts/check_phase1.ps1 -SkipSync`
  — **exit 0**. Stages: contract schema freshness; 266 tests passed in 8.59 s;
  Ruff clean; strict MyPy clean on 74 source files; dataset 6 fixtures, 40 query
  cases, 24 change cases valid; Phase 0 null baseline unchanged; Phase 1 engine
  baseline unchanged.
- Baseline reproducibility: generation and `--check` both exited 0.
- Manual console-script run: `repo add` exited 0; `index` exited 0 reporting
  `1 files, 1 parsed, 0 parse errors`; `symbol capture` exited 0 printing
  `src/service.py:2-3 [deterministic]`; `symbol NoSuchSymbol` exited 4.
- Artifacts: `baseline-phase-1.json` SHA-256
  `565046D74BD0FF61CDE36F37EC57AEDA0CCEAF01B9E86204E1F259E32A5E6762`;
  `baseline-phase-1.md` SHA-256
  `A4F3B0BE5183F9F5EB466D32D208E1785B37801142FFEA93DE00C73F82490BA6`.

#### Baseline results, stated honestly

The engine resolved **5 of 5** supported cases (`EXACT_SYMBOL` on `python_app`).
Aggregate metrics are low because 35 of 40 cases fall outside Phase 1 scope and
are emitted as explicit abstentions rather than wrong answers: exact symbol
resolution 0.1282, primary evidence Recall@10 0.0635, changed-symbol and impact
metrics 0.0000, unsupported-claim rate 0.0000. `targets_met` is `false`, which is
the correct result for a phase implementing one of nine intents.

`valid_evidence_rate` reads 0.8000. **That does not mean 20 percent of evidence
was invalid.** The metric counts exact agreement with gold
`(snapshot, path, start, end)` tuples. Every evidence item the engine emitted was
checked against fixture contents and all fell inside their file's real bounds;
none was invented. The single disagreement is `q009`, which expects lines 10-11
of `src/payments/service.py` while the engine returns the full definition range
7-11 — the same real method at a different granularity. The gold case was **not**
edited to raise the metric; doing so would destroy the corpus's value as an
independent check. Resolving it needs a product decision in a later phase.

#### Git state, corrected

An `initial commit` (`fb14126`) now exists on `main`; it was created during this
session, after several earlier handoffs had recorded "no commits yet". Those
entries were accurate when written and are left unmodified per rule 8. All Phase
1 work is currently **uncommitted** on top of that commit.

#### Limitations and follow-ups

- One query intent (`exact_symbol`); no relations, additional languages, change
  analysis, UI, or provider.
- Indexing is synchronous with no progress reporting or cancellation, and
  rebuilds fully on any change; incremental reuse is Phase 2.
- `status` reports snapshot-recorded freshness without re-verifying file drift;
  `lookup` verifies drift per query.
- UNC roots are rejected. A subdirectory of a Git repository indexes normally but
  records no Git state (`GIT_ROOT_MISMATCH`).
- The `q009` evidence-granularity disagreement described above.
- `starlette` warns that `httpx` in its test client is deprecated; this is
  dependency-side only with no behavioral effect.

#### Next: required decision

The user reviews Phase 1 and either approves the gate or requests changes. On
approval an agent records it here, sets P1-10 and Phase 1 to `complete`, and only
then prepares the Phase 2 plan.

### 2026-07-25T19:51:52Z — P1-09 completed; P1-10 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-09 `in_progress -> complete`; P1-10 `pending -> in_progress`.
- Outcome: Added the Typer CLI (`repo add`, `repo list`, `index`, `status`,
  `symbol`) with `--json` and human output, and the `apps/cli/main.py` entry
  point. CLI and REST build the same `ApplicationServices`, so they answer
  identically.
- Files: `src/codeatlas/cli/main.py`, `apps/cli/main.py`,
  `tests/end_to_end/test_cli_workflow.py`,
  `src/codeatlas/parsing/python_parser.py` (BOM fix),
  `src/codeatlas/application/lookup.py` (excerpt decoding).
- Contracts/migrations: `codeatlas symbol --json` emits the contract
  `QueryResponse` verbatim. Exit codes are now a public interface: 0 success,
  2 invalid input, 3 repository/snapshot unavailable, 4 partial or abstained,
  5 policy failure, 6 internal failure. No schema change.
- Verification (all exit code 0 unless stated): `uv run pytest
  tests/end_to_end/test_cli_workflow.py -q` — 11 passed in 1.83 s;
  `uv run pytest -q` — 251 passed in 8.28 s; Ruff — all checks passed; strict
  MyPy — no issues in 70 source files. Manual console-script run against a
  throwaway repository: `uv run codeatlas repo add` exited 0, `index` exited 0
  and reported `1 files, 1 parsed, 0 parse errors`, `symbol capture` exited 0 and
  printed `src/service.py:2-3 [deterministic]`, and `symbol NoSuchSymbol` exited
  4 with `NO_EXACT_SYMBOL_MATCH`.
- Defect found by manual verification and fixed (product bug, originally
  introduced in P1-05): a UTF-8 file with a byte-order mark failed to parse.
  `ast` treats a BOM as a syntax error, so every file written by
  `Set-Content -Encoding utf8` or a typical Windows editor was counted as a
  parse error and contributed no symbols. On a Windows-first product that is a
  significant correctness gap, and the automated suite missed it because every
  fixture was written without a BOM. The parser now strips the BOM before
  parsing and adds its byte length back to every span, so byte offsets still
  index the original file; evidence excerpts decode with `utf-8-sig` for the
  same reason. A regression test asserts success, correct line numbers, and a
  correct byte slice for BOM content.
- Cross-adapter agreement proven by test: indexing through the CLI and querying
  the same symbol through the CLI and through `TestClient` return the same
  snapshot ID, the same evidence ID, and the same file and line range.
- Security: a test asserts `--json` output contains no absolute path.
- Housekeeping: renamed the new CLI test module to `test_cli_workflow.py`
  because `tests/evaluation/test_cli.py` already claimed the module name and
  MyPy rejects duplicates.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: `index` blocks until the run finishes; there is no progress
  output and no cancellation.
- Next: P1-10 — Windows/security sweep, evaluation baseline, documentation, and
  the phase gate.

### 2026-07-25T19:47:23Z — P1-08 completed; P1-09 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-08 `in_progress -> complete`; P1-09 `pending -> in_progress`.
- Outcome: Added the `/v1` REST adapter over the existing application services:
  register, list, get, index, status, diagnostics, active snapshot, and query.
  The adapter validates input, calls a service, and serializes the result; it
  selects no evidence and adds no claim of its own.
- Files: `src/codeatlas/api/app.py`, `src/codeatlas/api/errors.py`,
  `src/codeatlas/api/routers/repositories.py`,
  `src/codeatlas/api/routers/query.py`, `apps/api/main.py`,
  `tests/contract/test_rest_api.py`, `tests/security/test_api_exposure.py`.
- Contracts/migrations: First public HTTP surface. `POST /v1/query` returns the
  contract `QueryResponse` unchanged; every error uses the contract
  `ErrorEnvelope`. No schema change.
- Verification (all exit code 0): tests written first and observed failing at
  import; `uv run pytest tests/contract/test_rest_api.py
  tests/security/test_api_exposure.py -q` — 19 passed in 2.84 s;
  `uv run pytest -q` — 239 passed in 7.52 s; Ruff — all checks passed; strict
  MyPy — no issues in 67 source files.
- Error mapping proven by test: 404 `REPOSITORY_NOT_FOUND`, 409
  `SNAPSHOT_NOT_READY` (retryable) and `REPOSITORY_ALREADY_REGISTERED`, 400
  `PATH_*`, `INVALID_REQUEST`, and `UNSUPPORTED_QUERY_MODE`, 422 for a malformed
  body, 500 `INTERNAL_ERROR`. An unmatched symbol returns 200 with an
  abstention, not an error — absence of a symbol is an answer, not a failure.
- Security: the server binds to `127.0.0.1` (asserted by test); no CORS
  middleware is registered (asserted by test); error bodies carry no stack
  trace, no absolute path, and no exception message — an injected route raising
  a secret-bearing exception returns only the opaque envelope; repository
  responses omit the absolute root; the FastAPI validation handler is replaced so
  submitted values are not echoed back.
- Deviation from the plan: the plan listed a per-request connection dependency.
  The app instead reuses one WAL connection with `check_same_thread=False`,
  closed by a lifespan handler. Phase 1 is a single-user single-writer local
  service, so a connection per request would add cost without removing any
  contention. Revisit if concurrent writers ever appear.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: indexing is synchronous, so `POST /index` blocks for the duration
  of the run; moving it to a job-polling contract is an additive Phase 6 change.
  `starlette` emits a deprecation warning about `httpx` in the test client; that
  is a dependency-side notice with no effect on behavior.
- Next: P1-09 — the minimal CLI adapter.

### 2026-07-25T19:43:07Z — P1-07 completed; P1-08 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-07 `in_progress -> complete`; P1-08 `pending -> in_progress`.
- Outcome: Added exact symbol lookup returning a contract `1.0` `QueryResponse`
  with snapshot-bound evidence, plus repository status and diagnostics services.
  The container now exposes all four services to adapters.
- Files: `src/codeatlas/application/lookup.py`,
  `src/codeatlas/application/status.py`,
  `src/codeatlas/application/container.py` (extended),
  `src/codeatlas/storage/sqlite/stores.py` (structured job diagnostics),
  `src/codeatlas/application/indexing.py` (records those diagnostics),
  `tests/integration/test_lookup.py`,
  `tests/contract/test_query_response_contract.py`,
  `tests/integration/test_stores.py` (updated for the new job diagnostics shape).
- Contracts/migrations: No schema change. `index_jobs.diagnostics` now holds a
  JSON object (`outcome`, `warnings`, `skipped_by_reason`, `parse_diagnostics`)
  instead of a JSON array, so status and diagnostics can explain a snapshot
  without re-scanning. The column type is unchanged, so no migration is needed.
- Verification (all exit code 0): tests written first and observed failing;
  `uv run pytest tests/integration/test_lookup.py
  tests/contract/test_query_response_contract.py -q` — 25 passed in 3.42 s;
  `uv run pytest -q` — 220 passed in 10.23 s; Ruff — all checks passed; strict
  MyPy — no issues in 60 source files.
- Trust behavior now proven by test:
  - evidence carries `derivation=deterministic` while its claim carries
    `derivation=static_resolved`; the fields stay distinct;
  - an unmatched query abstains with `NO_EXACT_SYMBOL_MATCH`, no claims, and no
    evidence — no invented path, line, or symbol;
  - a file edited after indexing is detected by content-hash comparison: the
    response is marked `stale`, the evidence is withheld, and
    `EVIDENCE_STALE_FILE_CONTENT` is returned;
  - a file deleted after indexing yields `EVIDENCE_FILE_UNREADABLE` and no
    evidence;
  - responses round-trip through `QueryResponse.model_validate_json`, every claim
    resolves to returned evidence, and all evidence shares the response's
    repository and snapshot.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: only `exact_symbol` intent is implemented. Excerpts are bounded to
  200 lines and 8000 characters. Status reports `freshness=fresh` from the
  snapshot record without re-verifying every file — drift is detected per query
  in `lookup`, not in `status`.
- Next: P1-08 — the `/v1` REST adapter.

### 2026-07-25T19:39:05Z — P1-06 completed; P1-07 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-06 `in_progress -> complete`; P1-07 `pending -> in_progress`.
- Outcome: Added repository registration, the indexing service, and the shared
  application container. A registered repository now scans, captures Git state,
  parses Python, stages a snapshot, validates it, and activates it atomically.
- Files: `src/codeatlas/application/registration.py`,
  `src/codeatlas/application/indexing.py`,
  `src/codeatlas/application/container.py`,
  `tests/integration/test_indexing.py`.
- Contracts/migrations: `INDEX_VERSION = "1.0.0"` joins `PARSER_BUNDLE_VERSION`
  as a truth-bearing input to snapshot identity. No schema change.
- Verification (all exit code 0): tests written first and observed failing with
  `ModuleNotFoundError: No module named 'codeatlas.application.container'`;
  `uv run pytest tests/integration/test_indexing.py -q` — 17 passed in 2.78 s;
  `uv run pytest -q` — 195 passed in 7.06 s; Ruff — all checks passed; strict
  MyPy — no issues in 56 source files.
- Invariants now proven end to end by test:
  - re-indexing an unchanged tree returns the same snapshot ID and creates no
    second snapshot row (idempotency);
  - editing a symbol produces a new active snapshot and supersedes the previous
    one;
  - an injected validation failure leaves the previous active snapshot intact
    and marks the new snapshot `failed`;
  - a non-Git directory still activates, carrying an explicit Git warning;
  - malformed Python is counted in `parse_error_count` and does not abort the
    run;
  - indexing never executes repository code.
- Transaction discipline: scanning, Git, and parsing run outside any
  transaction. Only the staged row writes and the activation swap are
  transactional, keeping write transactions short per `CLAUDE.md` Section 15.
- Correction made during review: a bare `assert` guarded the post-activation
  read. Asserts vanish under `-O`, so it now raises `SnapshotValidationError`
  rather than returning a snapshot the database does not agree exists.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: indexing is synchronous and in-process per ADR-0002; there is no
  cancellation yet. Full rebuilds happen on any change — incremental reuse is
  Phase 2.
- Next: P1-07 — exact symbol lookup, status, and diagnostics services.

### 2026-07-25T19:35:07Z — P1-05 completed; P1-06 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-05 `in_progress -> complete`; P1-06 `pending -> in_progress`.
- Outcome: Added the parser contracts, the language registry, and the Python
  parser. Both layers run for every file: `ast` is authoritative for structure,
  qualified names, decorators, async definitions, and exact line ranges, while
  Tree-sitter supplies definition byte spans and recovers symbols when `ast`
  rejects the file. Extracted kinds are MODULE, CLASS, FUNCTION, METHOD,
  CONSTRUCTOR, TEST, and CONSTANT.
- Files: `src/codeatlas/parsing/registry.py`,
  `src/codeatlas/parsing/python_parser.py`,
  `tests/unit/test_python_parser.py`, `tests/security/test_parser_safety.py`.
- Contracts/migrations: `PARSER_BUNDLE_VERSION = "1.0.0"` is now a truth-bearing
  input to `symbol_version_id` and `snapshot_id`. No schema change.
- Verification (all exit code 0): tests written first and observed failing with
  `ModuleNotFoundError: No module named 'codeatlas.parsing.python_parser'`;
  `uv run pytest tests/unit/test_python_parser.py
  tests/security/test_parser_safety.py -q` — 24 passed in 0.47 s;
  `uv run pytest -q` — 178 passed in 5.29 s; Ruff — all checks passed; strict
  MyPy — no issues in 52 source files.
- Behavior decisions recorded for later phases: a definition range starts at its
  first decorator; a `test_`-prefixed function is `TEST` only inside a file
  classified `TEST_CODE`, and stays `FUNCTION` elsewhere; `visibility` is
  `private` when any dotted part starts with an underscore; a module symbol
  carries the dotted module path with a trailing `.__init__` removed.
- Verified identity behavior: repeated parses produce identical `symbol_id` and
  `symbol_version_id`; editing a body changes `symbol_version_id` while
  `symbol_id` holds. Both are covered by tests, which is the Phase 2 reuse
  precondition.
- Security: tests prove module-level statements and import side effects are never
  executed, that the module contains no `exec`, `eval`, `importlib`,
  `__import__`, `runpy`, or `subprocess`, that oversized content is rejected
  before parsing, that undecodable bytes produce a diagnostic, and that malformed
  and deeply nested sources yield diagnostics instead of crashes.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: relations (imports, calls, inheritance) are not extracted — that
  is Phase 3. Docstrings are parsed but not yet stored. Only Python is
  registered.
- Next: P1-06 — indexing service, pre-activation validation, atomic activation.

### 2026-07-25T19:30:39Z — P1-04 completed; P1-05 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-04 `in_progress -> complete`; P1-05 `pending -> in_progress`.
- Outcome: Added the snapshot and symbol domain types, SQLite connection
  management with the ADR-0002 pragmas, the explicit numbered migration runner,
  migration `0001_phase1_repository_truth.sql`, and typed stores for
  repositories, snapshots, files, symbols, and index jobs.
- Files: `src/codeatlas/domain/snapshot.py`, `src/codeatlas/domain/symbols.py`,
  `src/codeatlas/storage/sqlite/connection.py`,
  `src/codeatlas/storage/sqlite/migrations.py`,
  `src/codeatlas/storage/sqlite/migrations/0001_phase1_repository_truth.sql`,
  `src/codeatlas/storage/sqlite/stores.py`, `pyproject.toml` (wheel
  force-include for the migration data files),
  `tests/integration/test_migrations.py`, `tests/integration/test_stores.py`.
- Contracts/migrations: **First storage migration.** `SCHEMA_VERSION = 1`
  creates `schema_migrations`, `repositories`, `snapshots`, `files`, `symbols`,
  and `index_jobs`. Forward-only; there is no earlier state and rollback is
  deletion of the database file.
- Verification (all exit code 0): tests written first and observed failing with
  `ModuleNotFoundError: No module named 'codeatlas.domain.snapshot'`;
  `uv run pytest tests/integration/test_migrations.py
  tests/integration/test_stores.py -q` — 25 passed in 0.68 s;
  `uv run pytest -q` — 154 passed in 4.39 s; Ruff — all checks passed; strict
  MyPy — no issues in 48 source files.
- Design decision made during implementation: `executescript` implicitly commits
  any pending transaction, which would leave a failed migration half applied.
  Migrations are therefore executed statement by statement inside an explicit
  `BEGIN IMMEDIATE`, with statement boundaries determined by
  `sqlite3.complete_statement` so a semicolon inside a literal cannot split a
  statement. A test proves a failing write transaction rolls back.
- Invariants enforced in the database rather than in code: a partial unique
  index makes a second active snapshot per repository impossible, `canonical_root`
  is unique, and foreign keys cascade from repository to snapshots, files, and
  symbols. Symbols reference `(snapshot_id, file_id)`, so a symbol cannot exist
  without its file in the same snapshot. All four are covered by tests.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: `find_exact` uses tiered exact matching only; lexical and fuzzy
  search belong to Phase 2. Migration downgrades are not supported.
- Next: P1-05 — parser registry and the Python parser.

### 2026-07-25T19:25:56Z — P1-03 completed; P1-04 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-03 `in_progress -> complete`; P1-04 `pending -> in_progress`.
- Outcome: Added the read-only Git state adapter. Every invocation uses a fixed
  argument array with `shell=False`, selects the repository through `cwd` rather
  than a positional path, disables terminal prompting and optional lock writes,
  and applies a 10-second timeout. Absent, slow, or non-Git conditions degrade to
  a warning code instead of raising.
- Files: `src/codeatlas/repositories/git_state.py`,
  `tests/integration/test_git_state.py`, `tests/conftest.py` (added the real
  `git_repo` fixture with per-command identity so it never depends on the
  developer's global Git configuration).
- Contracts/migrations: No contract or schema change.
- Verification (all exit code 0): tests written first and observed failing with
  `ModuleNotFoundError: No module named 'codeatlas.repositories.git_state'`;
  after the fix `uv run pytest tests/integration/test_git_state.py -q` — 11
  passed in 2.72 s; `uv run pytest -q` — 129 passed in 4.30 s; Ruff — all checks
  passed; strict MyPy — no issues in 41 source files.
- Defect found by testing (product behavior, not a test artifact): Git answers
  for the whole enclosing work tree, so a registered directory nested inside
  another repository inherited that repository's HEAD, branch, and dirty state.
  A snapshot would then have carried Git facts describing different content.
  The adapter now compares `rev-parse --show-toplevel` with the approved root
  and returns `GIT_ROOT_MISMATCH` with no Git facts when they differ. The
  behavior is covered by a test that registers a subdirectory of a real Git
  repository. Registering a subdirectory of a repository is therefore supported
  for scanning and indexing but yields no Git state; promoting it to
  parent-scoped Git facts would need an explicit product decision.
- Security: a test asserts the module contains no `shell=True` and no
  `os.system`; two tests register roots named like Git options
  (`--upload-pack=...`, `-c core.pager=x`) and confirm they degrade rather than
  execute an injected option.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: `is_dirty` includes untracked files by design. Timeout behavior is
  exercised with a zero-second timeout rather than a genuinely slow repository.
- Next: P1-04 — SQLite connection, migrations, and stores.

### 2026-07-25T19:22:17Z — P1-02 completed; P1-03 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-02 `in_progress -> complete`; P1-03 `pending -> in_progress`.
- Outcome: Added ignore-rule compilation with documented precedence, path-only
  file classification across all fifteen blueprint classes, and the deterministic
  bounded scanner that produces file records, reason-coded exclusions, warnings,
  and the working-tree fingerprint that later determines snapshot identity.
- Files: `src/codeatlas/repositories/ignore_rules.py`,
  `src/codeatlas/repositories/classification.py`,
  `src/codeatlas/repositories/scanner.py`, `tests/unit/test_ignore_rules.py`,
  `tests/unit/test_classification.py`, `tests/integration/test_scanner.py`.
- Contracts/migrations: No contract or schema change.
- Verification (all exit code 0): tests written first and observed failing with
  `ModuleNotFoundError: No module named 'codeatlas.repositories.ignore_rules'`;
  after implementation and two fixes `uv run pytest tests/unit/test_ignore_rules.py
  tests/unit/test_classification.py tests/integration/test_scanner.py -q` — 43
  passed in 0.55 s; `uv run pytest -q` — 118 passed in 1.42 s; Ruff — all checks
  passed; strict MyPy — no issues in 39 source files.
- Defects found and fixed during the task:
  1. Directory-only ignore patterns (`docs/`) did not exclude paths beneath the
     directory when queried directly. Matching now tests every ancestor prefix,
     so exclusion no longer depends on traversal order.
  2. The scanner derived an entry's relative path with `realpath`, so a junction
     escaping the root was reported as `PATH_REJECTED` under its target name
     instead of `OUTSIDE_ROOT` under its own name, and no
     `SECURITY_LINK_ESCAPE` warning was raised. Relative paths are now built
     from the walk itself and containment is decided separately.
  A third failure was a faulty test of mine, not a defect: it asserted a
  root-anchored `/build` rule while the built-in defaults already ignore
  `build/`. The test now uses a name that is not a built-in default.
- Security: link escapes are excluded with a warning, oversized and binary files
  are skipped by reason code, unreadable entries degrade instead of crashing,
  depth/file-count/path-length limits are enforced, and a test proves a
  module-level side effect in repository source is never executed.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: the ignore syntax subset excludes `**`, `?`, and character
  classes; such patterns are recorded as `IGNORE_PATTERN_UNSUPPORTED` warnings
  and deliberately not approximated.
- Next: P1-03 — Git state adapter.

### 2026-07-25T19:04:58Z — P1-01 completed; P1-02 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-01 `in_progress -> complete`; P1-02 `pending -> in_progress`.
- Outcome: Added the Phase 1 domain foundation — stable error codes and the
  `CodeAtlasError` hierarchy, derived logical/version identities, and the
  canonicalization and containment rules that every later path decision uses.
  Relative-path validity delegates to the existing `RepositoryRelativePath`
  contract rule rather than introducing a second validator.
- Files: `src/codeatlas/domain/errors.py`, `src/codeatlas/domain/ids.py`,
  `src/codeatlas/domain/paths.py`, `src/codeatlas/domain/repository.py`,
  `tests/conftest.py`, `tests/unit/test_domain_ids.py`,
  `tests/security/test_path_safety.py`.
- Contracts/migrations: No contract or schema change. `ErrorCode` is a new
  public enum consumed by later adapters.
- Verification (all exit code 0): tests were written first and observed failing
  with `ModuleNotFoundError: No module named 'codeatlas.domain.errors'`; after
  implementation `uv run pytest tests/unit/test_domain_ids.py
  tests/security/test_path_safety.py -q` — 25 passed in 0.28 s;
  `uv run pytest -q` — 75 passed in 1.18 s;
  `uv run ruff check src tests scripts apps` — all checks passed;
  `uv run mypy --no-incremental src tests scripts apps` — no issues in 33 source
  files.
- Security: traversal, absolute, backslash, blank, root-itself, Windows reserved
  device name, UNC, and a real Windows junction escape are all rejected and
  covered by tests. Containment compares `os.path.realpath` on both sides and
  case-folds on Windows.
- Git state: branch `main`, no commits yet, all files untracked.
- Limitations: UNC roots are rejected outright rather than supported behind an
  opt-in; that opt-in does not exist and is not in Phase 1 scope.
- Next: P1-02 — ignore rules, classification, scan limits, and the scanner.

### 2026-07-25T18:59:40Z — Phase 1 approved; P1-SETUP completed; P1-01 started

- Agent: Claude Code `claude-opus-5`
- Approval: User approved the Phase 1 plan and instructed agents to begin
  execution.
- Transition: Phase 1 `ready -> in_progress`; P1-SETUP `ready -> in_progress ->
  complete`; P1-01 `pending -> ready`.
- Outcome: Locked the Phase 1 dependencies, verified the Tree-sitter Python
  bundle loads, extended the tooling configuration, created the package
  skeleton, and recorded ADR-0002 for the storage and migration mechanism. No
  product behavior was implemented.
- Files: `pyproject.toml`, `uv.lock`,
  `docs/adr/0002-phase1-storage-and-migration-mechanism.md`, and twelve
  docstring-only `__init__.py` files under `src/codeatlas/` and `apps/`.
- Contracts/migrations: None. Contract `1.0` unchanged; no schema created yet.
- Dependencies locked: `tree-sitter==0.26.0`, `tree-sitter-python==0.25.0`,
  `fastapi==0.140.0`, `uvicorn==0.51.0`, `typer==0.27.0`, and dev
  `httpx==0.28.1`, with transitive `starlette==1.3.1`, `click==8.4.2`,
  `anyio==4.14.2`, `h11==0.16.0`, `rich==15.0.0`, `httpcore==1.0.9`,
  `certifi==2026.7.22`, `idna==3.18`, `annotated-doc==0.0.4`,
  `markdown-it-py==4.2.0`, `mdurl==0.1.2`, `shellingham==1.5.4`.
- Tooling: added `[project.scripts] codeatlas`, `pythonpath = ["src", "."]` so
  `apps.*` is importable in tests, `apps` added to the MyPy `files` list, and a
  narrow `tree_sitter_python` missing-stub override instead of weakening
  `strict`.
- Verification (all exit code 0):
  `uv run python -c "...tree_sitter..."` printed
  `(module (function_definition ...))`; `uv run pytest -q` — 50 passed in 1.14 s;
  `uv run ruff check src tests scripts apps` — all checks passed;
  `uv run mypy --no-incremental src tests scripts apps` — no issues in 26 source
  files; `powershell -ExecutionPolicy Bypass -File scripts/check_phase0.ps1
  -SkipSync` — completed with schema freshness, 50 tests, lint, types, dataset
  6/40/24 valid, and the tracked null baseline unchanged.
- Deviation: the plan's verification snippet used `Node.sexp()`, which is
  deprecated in `tree-sitter` 0.26; `str(node)` was used instead. Same assertion,
  same result.
- Git state: branch `main`, still no commits, all files untracked, so no commit
  SHA accompanies this entry.
- Limitations: `[project.scripts] codeatlas` points at
  `codeatlas.cli.main:main`, which does not exist until P1-09. The wheel builds,
  but invoking the console script fails until then.
- Next: P1-01 — path safety and repository identity domain, test-first.

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
