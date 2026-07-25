# CodeAtlas

CodeAtlas is a local-first repository-intelligence and change-assurance layer.
The implementation follows the authoritative requirements in `AGENTS.md` and
the shared execution state in `docs/plans/PLAN.md`.

## Windows development

Requirements: Windows 11, PowerShell 7 or Windows PowerShell 5.1, and `uv`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/check_phase0.ps1 -SkipSync
```

The quality command validates the tracked contract schema, tests, lint, types,
the evaluation corpus, and the honest null baseline. Repository fixtures are
untrusted data and are never imported, built, or executed.

See `docs/operations/development-windows.md` for commands and troubleshooting.
