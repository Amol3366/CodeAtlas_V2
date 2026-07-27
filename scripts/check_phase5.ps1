# Phase 5 release gate. Supersedes scripts/check_phase4.ps1.
#
# Phase 5 is the first phase with two runtimes, so the gate has two halves and
# runs them in the order a failure is cheapest to diagnose: the backend first
# (a broken contract makes every frontend check meaningless), then the
# generated types, then the web application.
#
# Playwright is deliberately not run here. It needs a live server and a real
# browser, which makes it slow and environment-dependent; it is run separately
# and its result recorded in the handoff, exactly as the performance
# measurement is.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$Command = "uv",
        [string]$WorkingDirectory
    )

    Write-Output "==> $Label"
    if ($WorkingDirectory) { Push-Location $WorkingDirectory }
    try {
        & $Command @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE."
        }
    } finally {
        if ($WorkingDirectory) { Pop-Location }
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Run scripts/setup_windows.ps1 first."
}

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps\web"

# Every command below uses repository-relative paths, so the gate must not
# depend on where it was invoked from. Anchoring here makes running it from a
# subdirectory — or from an editor — behave identically to running it from the
# root.
Set-Location $root

if (-not $SkipSync) {
    Invoke-Checked "Frozen dependency sync" @("sync", "--all-groups", "--frozen")
}

# --- Backend -------------------------------------------------------------

Invoke-Checked "Contract schema freshness" @(
    "run", "python", "scripts/export_contract_schema.py", "--check"
)
Invoke-Checked "Tests" @("run", "pytest", "-q")
Invoke-Checked "Lint" @("run", "ruff", "check", "src", "tests", "scripts", "apps")
Invoke-Checked "Types" @(
    "run", "mypy", "--no-incremental", "src", "tests", "scripts", "apps"
)
Invoke-Checked "Dataset validation" @(
    "run", "python", "scripts/run_evaluation.py", "validate",
    "--dataset", "tests/evaluation/cases"
)
Invoke-Checked "Phase 0 null baseline" @(
    "run", "python", "scripts/run_evaluation.py", "null-baseline",
    "--dataset", "tests/evaluation/cases",
    "--json-output", "docs/evaluation/baseline-phase-0.json",
    "--markdown-output", "docs/evaluation/baseline-phase-0.md",
    "--check"
)
Invoke-Checked "Phase 3 engine baseline" @(
    "run", "python", "scripts/run_phase3_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", "docs/evaluation/baseline-phase-3.json",
    "--markdown-output", "docs/evaluation/baseline-phase-3.md",
    "--check"
)
Invoke-Checked "Phase 4 engine baseline" @(
    "run", "python", "scripts/run_phase4_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", "docs/evaluation/baseline-phase-4.json",
    "--markdown-output", "docs/evaluation/baseline-phase-4.md",
    "--check"
)

if ($SkipWeb) {
    Write-Output "Phase 5 backend verification completed (web skipped)."
    exit 0
}

# --- Web -----------------------------------------------------------------

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm is required for the web gate. Run scripts/setup_windows.ps1."
}

# Generated types are checked before the web build: a stale client type is a
# backend/frontend disagreement, and finding it here names it as one.
& (Join-Path $PSScriptRoot "generate_web_types.ps1") -Check
if ($LASTEXITCODE -ne 0) {
    throw "Web API type check failed with exit code $LASTEXITCODE."
}

Invoke-Checked "Web lint" @("exec", "eslint", ".", "--max-warnings", "0") `
    -Command "pnpm" -WorkingDirectory $web
Invoke-Checked "Web types" @("exec", "tsc", "--noEmit") `
    -Command "pnpm" -WorkingDirectory $web
Invoke-Checked "Web tests" @("exec", "vitest", "run") `
    -Command "pnpm" -WorkingDirectory $web
Invoke-Checked "Web build" @("exec", "vite", "build") `
    -Command "pnpm" -WorkingDirectory $web

Write-Output "Phase 5 verification completed."
