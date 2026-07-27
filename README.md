# CodeAtlas

CodeAtlas is a local-first repository-intelligence and change-assurance layer.
The implementation follows the authoritative requirements in `CLAUDE.md` and
the shared execution state in `docs/plans/PLAN.md`.

## What works today (Phase 4)

Register a local repository, index Python/TypeScript/JavaScript into a
validated snapshot with a cross-file relation graph, search it, traverse it,
and run change preflight — through the application services, the `/v1` REST
API, the CLI, and MCP, all sharing one implementation.

```powershell
uv run codeatlas repo add C:\path\to\repository --json
uv run codeatlas index <repository_id>
uv run codeatlas symbol <repository_id> PaymentService.capture
uv run codeatlas search text <repository_id> "idempotency key"
uv run codeatlas graph callers <repository_id> PaymentService.capture
uv run codeatlas impact <repository_id>            # working tree vs HEAD
uv run codeatlas impact <repository_id> --commits HEAD~1..HEAD --format sarif
```

Change preflight reports changed files and symbols, bounded impact paths,
related tests and documents, architecture-rule violations, and risk-ordered
findings — every finding citing hash-verified file-and-line evidence, with
base-side evidence labeled historical. See
`docs/operations/change-analysis.md`.

Every answer is bound to a snapshot. If a file changed after indexing, CodeAtlas
withholds the evidence and says so rather than citing content that no longer
matches. If nothing matches, it abstains rather than guessing.

The web application in `apps/web` adds persistent conversations, an evidence
drawer, and change preflight — see `docs/operations/web-application.md`. It
answers deterministically: there is no LLM, and an unanswerable question
produces an explicit abstention. Not built: the filesystem watcher and
packaging (Phase 6), and embeddings or any model provider (Phase 7). See
`docs/plans/PLAN.md` for the phase order.

## Windows development

Requirements: Windows 11, PowerShell 7 or Windows PowerShell 5.1, `uv`, and
— from Phase 5 onward — Node.js 20+ with pnpm (`corepack enable pnpm`) for
the web application in `apps/web`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/check_phase5.ps1 -SkipSync
```

The quality command validates the tracked contract schema, tests, lint, types,
the evaluation corpus, and the tracked Phase 1–4 baselines. Repository
fixtures are untrusted data and are never imported, built, or executed.

- `docs/operations/development-windows.md` — setup and the Phase 0 gate
- `docs/operations/development-windows-phase1.md` — CLI, API, and Windows behavior
- `docs/operations/relations-and-graph.md` — the relation graph and traversal
- `docs/operations/change-analysis.md` — change preflight and its limits
- `docs/operations/web-application.md` — the web app, its rules, and its limits
- `docs/evaluation/phase-4-baseline-environment.md` — how to read the baseline and performance numbers
- `docs/security/threat-model.md` — controls and their enforcement status
