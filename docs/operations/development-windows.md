# Windows Development and Phase 0 Verification

## Supported Baseline

- Windows 11
- PowerShell 7 or Windows PowerShell 5.1
- `uv`
- CPython 3.12, installed and selected by `uv`

No repository fixture may be imported, installed, built, tested, or executed.

## Setup

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
```

The script verifies `uv` and runs `uv sync --all-groups --frozen`. The lockfile
is authoritative; setup does not upgrade dependencies.

## Complete Phase 0 Check

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase0.ps1 -SkipSync
```

Omit `-SkipSync` in a clean environment. The command fails immediately when the
contract schema is stale, a test fails, lint/type checks fail, the corpus is
invalid, or baseline generation fails.

Individual commands:

```powershell
uv run python scripts/export_contract_schema.py --check
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy --no-incremental src tests scripts
uv run python scripts/run_evaluation.py validate --dataset tests/evaluation/cases
uv run python scripts/run_evaluation.py null-baseline `
  --dataset tests/evaluation/cases `
  --json-output docs/evaluation/baseline-phase-0.json `
  --markdown-output docs/evaluation/baseline-phase-0.md `
  --check
```

To intentionally regenerate the baseline after an approved evaluation-contract
change, run the same `null-baseline` command once without `--check`, review the
artifact diff, then rerun the full Phase 0 check.

## Troubleshooting

- If uv cannot access its cache, grant the current user access to uv's cache
  directory or set a task-specific `UV_CACHE_DIR` to a writable location.
- If test temporary directories are restricted, run from an account that can
  write to the repository-local `.test-tmp` directory.
- Do not bypass `--frozen`; update dependencies only as a separately reviewed
  change that intentionally regenerates `uv.lock`.
- If a platform-specific check cannot run, record the exact command, exit code,
  and limitation in `docs/plans/PLAN.md`. Never report it as passed.
