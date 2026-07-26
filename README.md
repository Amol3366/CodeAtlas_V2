# CodeAtlas

CodeAtlas is a local-first repository-intelligence and change-assurance layer.
The implementation follows the authoritative requirements in `CLAUDE.md` and
the shared execution state in `docs/plans/PLAN.md`.

## What works today (Phase 1)

Register a local repository, index it into a validated snapshot, and resolve an
exact Python symbol to verified file-and-line evidence — through the application
services, the `/v1` REST API, and the CLI, all sharing one implementation.

```powershell
uv run codeatlas repo add C:\path\to\repository --json
uv run codeatlas index <repository_id>
uv run codeatlas symbol <repository_id> PaymentService.capture
```

```text
PaymentService.capture is defined in src/payments/service.py lines 7-8.
  src/payments/service.py:7-8  [deterministic]
```

Every answer is bound to a snapshot. If a file changed after indexing, CodeAtlas
withholds the evidence and says so rather than citing content that no longer
matches. If nothing matches, it abstains rather than guessing.

Not yet built: TypeScript/JavaScript parsing, relations and graph traversal,
change analysis, chat or web UI, embeddings, and any model provider. See
`docs/plans/PLAN.md` for the phase order.

## Windows development

Requirements: Windows 11, PowerShell 7 or Windows PowerShell 5.1, and `uv`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/check_phase2.ps1 -SkipSync
```

The quality command validates the tracked contract schema, tests, lint, types,
the evaluation corpus, and the tracked Phase 0 and Phase 2 baselines. Repository fixtures are
untrusted data and are never imported, built, or executed.

- `docs/operations/development-windows.md` — setup and the Phase 0 gate
- `docs/operations/development-windows-phase1.md` — CLI, API, and Windows behavior
- `docs/evaluation/phase-1-baseline-environment.md` — how to read the baseline
- `docs/security/threat-model.md` — controls and their enforcement status
