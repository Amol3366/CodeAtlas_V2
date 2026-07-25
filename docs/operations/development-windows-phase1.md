# Windows Development and Phase 1 Verification

Phase 0's document covers setup and the contract/evaluation gate. This one covers
running and verifying the Phase 1 engine.

## Supported Baseline

- Windows 11
- PowerShell 7 or Windows PowerShell 5.1
- `uv`, CPython 3.12
- `git` on `PATH` (optional: repositories without Git index normally)

No repository being indexed is ever imported, installed, built, or executed.

## Complete Phase 1 Check

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase1.ps1 -SkipSync
```

Omit `-SkipSync` in a clean environment. The script fails on the first failure
and covers: contract schema freshness, the full test suite, Ruff, strict MyPy,
dataset validation, the Phase 0 null baseline, and the Phase 1 engine baseline.

Individual commands:

```powershell
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run python scripts/run_phase1_baseline.py `
  --dataset tests/evaluation/cases `
  --json-output docs/evaluation/baseline-phase-1.json `
  --markdown-output docs/evaluation/baseline-phase-1.md `
  --check
```

## Using the CLI

```powershell
uv run codeatlas repo add C:\path\to\repository --db .test-output\local.sqlite --json
uv run codeatlas index <repository_id> --db .test-output\local.sqlite
uv run codeatlas status <repository_id> --db .test-output\local.sqlite
uv run codeatlas symbol <repository_id> PaymentService.capture --db .test-output\local.sqlite
```

Omit `--db` to use `%LOCALAPPDATA%\CodeAtlas\data\codeatlas.db`. Set
`CODEATLAS_DB_PATH` to override it for a whole session.

Exit codes: `0` success, `2` invalid input, `3` repository or snapshot
unavailable, `4` partial or abstained result, `5` policy failure (path safety or
scan limits), `6` internal failure.

## Running the local API

```powershell
uv run python apps/api/main.py
```

Serves on `http://127.0.0.1:8765` and binds to loopback only. Interactive docs
are at `/docs`.

```powershell
$body = @{ path = "C:\path\to\repository" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/repositories -Body $body -ContentType application/json
```

## Known Windows Behavior

- A repository path is case-insensitive for identity: `C:\Repos\Demo` and
  `c:\repos\demo` register as the same repository, and registering the second
  after the first returns `REPOSITORY_ALREADY_REGISTERED`.
- UNC paths (`\\server\share`) are rejected. Supporting them requires an
  explicit opt-in that does not exist yet.
- A junction pointing outside the repository root is excluded with a
  `SECURITY_LINK_ESCAPE` warning. A junction pointing inside is followed.
- Files written with a UTF-8 byte-order mark (PowerShell's
  `Set-Content -Encoding utf8` on Windows PowerShell 5.1, and many editors) parse
  correctly.
- Registering a subdirectory of a Git repository indexes normally but records no
  Git state, reported as `GIT_ROOT_MISMATCH`. Register the repository root to
  capture branch and commit.

## Troubleshooting

- `SNAPSHOT_NOT_READY` means the repository was registered but never indexed.
  Run `codeatlas index <repository_id>`.
- `EVIDENCE_STALE_FILE_CONTENT` means the file changed after indexing.
  Re-index; CodeAtlas withholds evidence rather than citing content that no
  longer matches.
- If a platform-specific check cannot run, record the exact command, exit code,
  and limitation in `docs/plans/PLAN.md`. Never report it as passed.
