# PRD — CodeAtlas

Status: current as of 2026-08-04
Authority note: this file describes the product in plain language. The
release-blocking contract is `AGENTS.md`; the deep technical rationale is
`CODEATLAS_INDUSTRY_BLUEPRINT_2026.md`. Where this file and `AGENTS.md`
disagree, `AGENTS.md` wins.

## Problem

Before someone submits a change, they have to guess what it might break. The
answers are scattered across the diff, the test suite, the import graph, a
half-remembered architecture rule, and whatever a teammate happens to know.
Asking an AI assistant instead is faster but worse: it will confidently name a
file that does not exist, cite a line that moved three commits ago, or explain
a function it never read. The developer is left doing the verification work
anyway, now with extra text to disprove.

CodeAtlas answers the question with evidence attached — real file paths, real
line ranges, taken from a known snapshot of the repository — and says
"I don't know" when it does not know.

## Target Users

**The developer about to commit.** They have edits in their working tree, they
are reasonably confident, and they want a second opinion before they push. They
open CodeAtlas from the CLI or the local web app and ask what their change
touches.

**The reviewer opening someone else's diff.** They did not write the code, they
do not know the blast radius, and the PR description says "small refactor". They
want the affected symbols, the tests that cover them, and the architecture rules
the change crosses.

**A coding agent working in the repository.** It connects over MCP, needs facts
it can act on rather than plausible prose, and must be able to tell the
difference between a resolved fact and a guess.

All three share the same constraint: the source code stays on the workstation
unless the user explicitly says otherwise, per repository.

## Core Features

1. **Change preflight** — point at the working tree or a commit range and get
   the changed symbols, what depends on them, the affected tests and documents,
   and any architecture-rule violations, ordered by risk. This is the product.
2. **Evidence-grounded answers** — ask a question about the repository and get
   an answer where every material claim carries evidence IDs resolving to a
   file, a symbol, and a line range in a named snapshot.
3. **Explicit abstention** — when the evidence does not support a claim,
   CodeAtlas says so instead of producing one. A "don't know" is a successful
   outcome, not a failure.
4. **Freshness you can see** — every answer names the snapshot it came from and
   how current that snapshot is. A watcher keeps snapshots fresh; a reconciling
   scan corrects what the event stream drops.
5. **Persistent conversation history** — chat threads survive browser and
   backend restarts, and an old citation keeps the snapshot label it was
   answered against rather than being silently relabelled as current.
6. **Four ways in, one brain** — CLI, local REST API, MCP, and the web app all
   call the same application services and return the same evidence model.
7. **Reports for other tools** — JSON as the canonical form, Markdown for
   humans, SARIF 2.1.0 for scanners.
8. **Optional semantic recall** — embeddings improve *finding* candidates for
   conceptual questions. They never promote a candidate to a fact.
9. **Optional written explanation** — a local (Ollama) or hosted (OpenAI) model
   may write prose over evidence already gathered. It cannot change the
   citations, the line numbers, or the confidence.

## Non-Goals

- **Not an IDE.** No editor, no Monaco, no autocomplete.
- **Not an autonomous code editor.** CodeAtlas reads and reports; it does not
  modify source.
- **Not "chat with your codebase".** An LLM response is never repository truth.
- **Not a replacement** for compilers, language servers, tests, SAST, SCA, or
  CI. It reports on them, it does not become them.
- **Not cloud-first.** No mandatory network dependency. Nothing leaves the
  machine without a per-repository opt-in.
- **No multi-user tenancy, RBAC, billing, or enterprise control plane.**
- **No GitHub/GitLab or CI integration.**
- **No network exposure beyond loopback.**
- **No new languages beyond Python, TypeScript, and JavaScript** (plus Markdown
  and common config/schema formats) without an approved ADR.
- **No PostgreSQL, message broker, microservices, or Kubernetes.** SQLite is the
  system of record.

## Success Criteria

- A developer registers a local repository, indexes it, and gets a change
  preflight report on their working tree — with warm p95 under 10 seconds on
  the declared fixture profile.
- 100% of evidence resolves to a valid file and line range in the snapshot it
  claims, and zero results contain entities from another snapshot.
- The unsupported-factual-claim rate stays under 2%.
- Every deterministic capability still works with no embedding model, no LLM,
  and no network.
- A conversation opened a week later still shows which snapshot answered it.

The full measurable target table is `AGENTS.md` Section 19.3, which is the
release authority; the list above is the human summary of it.

## Current Status

Phases 0–7 are complete with user-approved gates. Three targets were accepted
as missed at their gates and remain open rather than being quietly dropped:
changed-symbol precision 0.9375 (structural, explained in
`docs/evaluation/phase-4-baseline-environment.md`), primary evidence Recall@10
0.6667 against a ≥0.90 target, and a packaged tree of 1.05 GB when the semantic
extras are installed. See `phases.md` for the full carried-forward list.

Post-gate work since then has improved usability without changing the evidence
contract: the Settings page has a professional provider layout, known warning
codes render as plain-language notes, known OpenAI embedding dimensions are
auto-resolved from the selected model, and the Ollama answer model can be
downloaded from Settings through a dedicated pull endpoint. The exact
`uv run codeatlas serve --web --open` path was verified on 2026-08-04 with the
new bundle and non-cacheable shell headers. One user browser session still
showed the older Settings view until manual reload; no further investigation is
active after the user said to leave it.
