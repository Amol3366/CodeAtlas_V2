# CodeAtlas V2 Working Guide

Status: current orientation document as of 2026-08-07

Authority note: this file explains CodeAtlas V2 in one readable place. The
release-blocking contract is `../AGENTS.md`; live task status is
`../docs/plans/PLAN.md`; product rationale is
`../CODEATLAS_INDUSTRY_BLUEPRINT_2026.md`. If this document disagrees with
th	ose authorities, this document is the bug.

## One Sentence

CodeAtlas is a local-first repository intelligence and change-assurance layer
that tells developers and coding agents what changed, what may be affected, and
what evidence proves it.

It is not an IDE, not a generic chat wrapper, and not a tool that treats an LLM
answer as repository truth. It builds its own snapshot of a repository and
answers from validated files, symbols, relations, search hits, Git changes, and
evidence.

## Why It Exists

Modern developers and AI coding agents can change code quickly. The slow and
risky part is verifying the blast radius:

- Which files and symbols actually changed?
- Which callers, dependencies, tests, docs, configs, or schemas may be affected?
- Which architecture rules were crossed?
- Is the answer based on the current repository state?
- Can a reviewer verify the answer without trusting prose?
- What does the tool not know?

CodeAtlas is built for that verification step. Its flagship workflow is
**change preflight**: before a commit or pull request, run an evidence-backed
analysis of the local working tree or a commit range.

## The Mental Model

Think of CodeAtlas as five layers:

1. **Repository registration**
   A local repository path is approved and stored. CodeAtlas records repository
   identity and Git state, but source is not executed.
2. **Snapshot indexing**
   The repository is scanned, parsed, chunked, indexed, and validated into an
   active snapshot. A snapshot is the unit of truth.
3. **Repository intelligence**
   CodeAtlas can resolve symbols, search text, traverse relations, inspect Git
   changes, map tests and docs, and optionally retrieve semantic candidates.
4. **Evidence validation**
   Every material claim must cite evidence that resolves to a file, line range,
   symbol, relation, or finding in the selected snapshot.
5. **Delivery surfaces**
   The same application services power the CLI, REST API, MCP tools, and web
   app. The frontend does not own repository truth.

The short version:

```text
local repo
  -> validated snapshot
  -> exact / lexical / graph / Git / optional semantic retrieval
  -> verified evidence
  -> answer, report, or preflight finding
```

## The Trust Contract

CodeAtlas is intentionally strict:

- No source leaves the machine unless a provider is enabled for that repository.
- Indexing never imports, builds, tests, or executes repository code.
- Exact lookup, parsing, Git diff mapping, graph traversal, architecture rules,
  and evidence validation do not depend on an LLM.
- Missing evidence causes abstention, warning, or claim rejection.
- Stale evidence is withheld rather than silently reused.
- Semantic results stay labeled `semantic_candidate`.
- Generated prose can explain evidence, but cannot change citations, line
  numbers, claims, derivation, or confidence.

This is the main product difference: CodeAtlas tries to make repository claims
auditable, not merely plausible.

## Main Functions and Scenarios

### 1. Add a Repository

Use this when you want CodeAtlas to know about a local repo.

```powershell
uv run codeatlas repo add C:\path\to\repository --json
```

What happens:

- The path is canonicalized and checked.
- Traversal, reserved names, UNC behavior, symlinks, and Windows junctions are
  handled according to the path-safety rules.
- Git state is captured when the registered root is a valid Git root.
- No source code is executed.

Scenario: a developer opens a local service repo and wants CodeAtlas to analyze
it before work begins.

### 2. Index a Repository

Use this to build the active repository snapshot.

```powershell
uv run codeatlas index <repository_id>
```

What happens:

- Files are scanned with ignore rules and safety limits.
- Python, TypeScript, JavaScript, Markdown, and common config/schema formats are
  parsed or classified.
- Symbols, chunks, lexical search rows, relations, and evidence candidates are
  stored in SQLite.
- Validation checks snapshot membership, relation endpoints, evidence ranges,
  FTS rows, and required version metadata.
- Activation is atomic: an interrupted index leaves the previous active
  snapshot usable.

Scenario: after adding a repo, a developer builds the first trusted snapshot.

### 3. Keep the Index Fresh

Use this when you want CodeAtlas to react to file changes.

```powershell
uv run codeatlas repo watch <repository_id>
uv run codeatlas repo watch <repository_id> --enable
uv run codeatlas repo watch <repository_id> --disable
```

What happens:

- Filesystem events are treated as triggers, not truth.
- Events are debounced so half-written saves are not indexed immediately.
- A reconciling scan catches events the filesystem watcher missed.
- Content hashes decide what actually changed.

Scenario: a developer edits code all day and wants CodeAtlas to stay current
without manually running `index` after each save.

### 4. Exact Symbol Lookup

Use this when you know the symbol you care about.

```powershell
uv run codeatlas symbol <repository_id> PaymentService.capture
```

What happens:

- Exact symbol resolution runs first.
- If evidence is valid, the answer names the file and line range.
- If the indexed file changed on disk, evidence is withheld with a stale-content
  warning.

Scenario: an agent is about to edit `PaymentService.capture` and needs the real
definition range and snapshot-bound evidence.

### 5. Keyword / Lexical Search

Use this when you want literal text or path matches.

```powershell
uv run codeatlas search <repository_id> "idempotency key" --kind text
```

What happens:

- Search uses FTS5, with a validated query builder.
- User text is treated as data, not FTS syntax.
- Lexical evidence is labeled as a heuristic text match, not proof of behavior.

Scenario: a reviewer wants to find where a phrase, config key, endpoint, or
error code appears.

### 6. Semantic Search and Hybrid Retrieval

Use this when the question is conceptual and literal keywords may miss relevant
chunks.

Semantic retrieval is optional. It requires a repository provider setting and
the relevant dependency extra:

```powershell
uv sync --extra semantic-local
uv sync --extra semantic-openai
```

What happens:

- Exact, lexical, graph, and Git retrieval remain available without semantic
  dependencies.
- Semantic retrieval is used for conceptual text and project overview answers.
- Semantic hits are fused into the answer as appended candidates.
- They are hash-verified and line-validated like other evidence.
- They are labeled `semantic_candidate` and cannot support an authoritative
  finding on their own.

Important distinction:

CodeAtlas has hybrid retrieval in the answer pipeline, but it does not expose a
single score-blended "hybrid search" endpoint. Keyword/lexical evidence is not
mixed into one opaque ranking with vector scores. The channels keep their
derivation labels so a user can see why something appeared.

Scenario: a user asks "How does order cancellation work?" and CodeAtlas can
combine lexical matches with semantically similar chunks, while still showing
which results are deterministic text matches and which are semantic candidates.

### 7. Graph Queries

Use this to ask about callers, callees, dependencies, related tests, related
documents, or traces.

```powershell
uv run codeatlas callers <repository_id> PaymentService.capture
```

What happens:

- CodeAtlas resolves the symbol.
- It traverses stored relations within bounded depth and visited-node limits.
- Ambiguous or truncated graph results are reported with warnings and
  limitations.

Scenario: before changing a payment method, an agent asks who calls it and what
tests or docs are nearby.

### 8. Change Preflight

This is the core product workflow.

```powershell
uv run codeatlas impact <repository_id>
uv run codeatlas impact <repository_id> --commits HEAD~1..HEAD --format sarif
```

What happens:

- Working-tree mode compares the current working tree against a base ref,
  usually `HEAD`.
- Commit-range mode compares two Git states.
- Diff hunks are mapped to syntax ranges.
- Changed files and changed symbols are identified.
- Direct and bounded transitive impact are computed from relations.
- Related tests, documents, config, schemas, and architecture rules are added.
- Findings are risk-ordered and cite evidence.
- Output can be JSON, Markdown, or SARIF.

Scenario: before opening a pull request, a developer runs preflight and gets a
review packet: changed symbols, likely blast radius, tests to run, docs likely
affected, and exact evidence.

### 9. Web Conversations

Use this when you want a ChatGPT-style interface backed by repository evidence.

```powershell
uv run codeatlas serve --web --open
```

What happens:

- FastAPI serves both `/v1` and the built web app from loopback.
- Conversations are stored on the backend, not only in the browser.
- Message submission is accept-then-stream: the request returns IDs, the answer
  runs on a worker, and the UI follows it over SSE.
- History survives restarts in default mode.
- Old citations keep the snapshot they were answered against.

Scenario: a developer asks "Where is checkout validation handled?" and opens
inline citations to inspect the exact evidence.

### 10. Evidence Panel

Use this when you need to verify a claim.

What happens:

- Inline `[n]` citation buttons open evidence on demand.
- The panel shows file path, symbol, line range, derivation, confidence, and
  snapshot.
- Evidence excerpts render as text, not unsafe HTML.
- If evidence cannot be verified, CodeAtlas refuses to display current file
  contents under an old citation.

Scenario: a reviewer clicks a citation in the answer before trusting a claim.

### 11. Settings and Providers

Use this to configure optional semantic retrieval or answer generation.

What happens:

- The default provider is `none`.
- Local embeddings use sentence-transformers and transmit nothing.
- OpenAI embeddings transmit and require explicit repository opt-in.
- Answer generation can use Ollama locally or OpenAI with a budget.
- `.env` supplies credentials and model identity, but never consent.
- The OpenAI API key can be entered in Settings and is stored in the Windows
  Credential Manager.
- No response returns the key or any part of it.

Scenario: one repository can use local embeddings while another stays fully
deterministic.

### 12. Ephemeral Sessions

Use this when developing CodeAtlas itself and you want every app run to start
fresh.

```powershell
uv run codeatlas serve --web --ephemeral --open
```

What happens:

- A temporary database and vector directory are created for this process.
- The real database is never opened.
- Repositories, snapshots, embeddings, and conversations start empty.
- Data is discarded when the server stops.

Scenario: while testing onboarding or indexing behavior, you want no old
repositories or conversations to influence what you see.

### 13. Backup, Restore, Upgrade, and Packaging

Use these when operating CodeAtlas as a local product.

```powershell
uv run codeatlas backup C:\backups\codeatlas.sqlite
uv run codeatlas restore C:\backups\codeatlas.sqlite
uv run codeatlas upgrade
dist\codeatlas-win64\codeatlas.exe serve --web --open
```

What happens:

- Backup uses SQLite's online backup API.
- Restore validates integrity and schema before replacing anything.
- Migrations write a verified checkpoint first.
- A build pointed at a newer database refuses rather than guessing.
- The packaged build serves the API and web app from one loopback origin.

Scenario: before installing a newer build, CodeAtlas protects the current
database and refuses unsafe downgrade behavior.

### 14. MCP and Agent Workflows

Use this when a coding agent needs repository facts.

The same application services support MCP tools for repository registration,
status, search, symbol resolution, graph traversal, evidence retrieval, and
change analysis.

Scenario: an AI coding agent asks CodeAtlas for context before editing, then
runs change preflight after editing to verify blast radius.

## Common End-to-End Scenarios

### Scenario A: Developer Checks Work Before Commit

1. Register and index the repo.
2. Edit code.
3. Let the watcher refresh, or run `index`.
4. Run `impact`.
5. Read changed symbols, affected areas, related tests/docs, warnings, and
   limitations.
6. Export Markdown or SARIF if needed.

Outcome: the developer submits a change with an evidence-backed review packet.

### Scenario B: Coding Agent Plans a Safe Edit

1. Resolve the target symbol.
2. Ask for callers, callees, dependencies, tests, and docs.
3. Edit source code outside CodeAtlas.
4. Run change preflight.
5. Use CodeAtlas findings to decide whether more tests or docs need changes.

Outcome: the agent is not judging its own change only from prose. It asks an
independent evidence layer.

### Scenario C: Reviewer Investigates a Risky Change

1. Run commit-range preflight.
2. Open high-severity findings first.
3. Click citations to verify exact file lines.
4. Check limitations to see what CodeAtlas could not prove.

Outcome: review time moves from reconstructing context to checking evidence.

### Scenario D: User Asks a Repository Question

1. Ask through the web app or API.
2. CodeAtlas classifies the intent.
3. It uses exact, lexical, graph, Git, and optional semantic retrieval as
   appropriate.
4. It cites evidence and abstains if support is missing.

Outcome: the answer is explainable and tied to a snapshot.

### Scenario E: Optional LLM Explanation

1. Enable an answer provider per repository.
2. Ask a question.
3. CodeAtlas gathers verified evidence first.
4. The model writes summary prose over that evidence.
5. Claims, citations, confidence, and line ranges remain unchanged.

Outcome: prose improves readability without becoming the source of truth.

## How CodeAtlas Is Different

### Different From an IDE

An IDE helps you write and navigate code. CodeAtlas verifies repository facts
and change impact. It does not edit source, run autocomplete, or become a code
editor.

### Different From Generic Code Search

Search finds matching text. CodeAtlas also tracks snapshots, symbols,
relations, evidence validity, freshness, impact, and limitations.

### Different From "Chat With Your Codebase"

Many chat tools answer from retrieved context. CodeAtlas requires material
claims to cite validated evidence and explicitly abstains when it cannot prove
the claim.

### Different From AI PR Review

AI PR reviewers usually comment on a pull request. CodeAtlas is designed to run
before the PR too, locally, with the working tree still on the developer's
machine.

### Different From Static Analysis

Static analyzers find rule violations. CodeAtlas uses static structure too, but
its workflow is broader: change impact, related tests/docs, evidence packets,
conversation history, provider governance, and agent-facing contracts.

### Different From Semantic Search Products

Semantic search improves recall. CodeAtlas treats semantic hits as discovery
candidates, not authoritative facts. It preserves the difference between an
exact relation and a nearest-neighbor match.

## Why This Can Be Superior

CodeAtlas can win when the user values trust over convenience:

- Local-first default.
- No mandatory model service.
- Deterministic fallback.
- Snapshot-bound citations.
- Stale evidence rejection.
- Explicit unknowns and limitations.
- Shared contracts across CLI, REST, MCP, and web.
- Change preflight as the primary workflow.

The strongest product position is:

```text
Cursor helps write code.
Sourcegraph helps search code.
AI review tools comment on PRs.
Semgrep finds rule violations.
CodeAtlas verifies local changes before they leave the machine.
```

## Current Product Status

Phases 0 through 7 are complete with user-approved gates. Current post-gate
features include:

- optional semantic retrieval;
- governed answer providers;
- `.env` provider configuration;
- per-repository local embedding model selection;
- frontend OpenAI credential entry through Windows Credential Manager;
- inline citation buttons and an on-demand evidence panel;
- ephemeral session mode;
- packaged Windows build;
- backup, restore, upgrade, watcher, recovery, and release validation flows.

Schema version is 14. Contract version is 1.1.

## Known Limits and Open Gaps

These are not hidden:

- Language coverage is focused on Python, TypeScript, JavaScript, Markdown, and
  common config/schema formats. A repository in any other language yields no
  symbols and no relations. **Java shipped 2026-08-19 (ADR-0065)** through a shared
  query-backed parser — symbols, imports, calls and changed-symbol detection,
  but no test edges and no route detection. Go, Rust and Scala are approved and
  not yet built.
- The packaged executable is unsigned.
- Some Chromium conversation-route Playwright tests are skipped because of a
  browser renderer crash; Firefox proves the workflow.
- Crash recovery does not detect PID reuse.
- The semantic-local packaged tree is large because of the torch dependency.
- Phase 7 Recall@10 improved but missed the declared target.
- Phase 4 changed-symbol precision missed the target for a structural corpus
  reason that is documented.
- There is no GitHub/GitLab/CI integration yet.
- There is no multi-user tenancy or enterprise control plane.

## Best Next Improvements

The most valuable improvements should strengthen the wedge rather than broaden
the product too early:

1. Make change preflight feel like the flagship screen and command.
2. Improve test and document impact mapping.
3. Add a polished PR-ready Markdown export flow.
4. Add stronger framework intelligence for routes, schemas, and config.
5. Improve lexical/conceptual retrieval quality before adding heavier AI.
6. Build agent-native workflows around "before edit" and "after edit" checks.
7. Clean stale documentation notes so the project story is consistent.
8. Decide code signing for the packaged executable.

## Glossary

**Snapshot**
The validated repository state CodeAtlas answers from.

**Evidence**
A file/symbol/line-range citation that resolves against a snapshot.

**Derivation**
How a claim was produced: deterministic, static resolved, heuristic, semantic
candidate, model generated, or unsupported.

**Freshness**
Whether the answer's snapshot and evidence still match the repository state.

**Change preflight**
The workflow that analyzes working-tree or commit-range changes and reports
changed symbols, likely impact, related tests/docs/config, findings, warnings,
and evidence.

**Semantic candidate**
A semantically similar chunk. Useful for discovery, but not authoritative on
its own.

**Accept-then-stream**
The conversation submission model where the server accepts a message, returns
IDs, runs the answer asynchronously, and streams progress/events to the client.
