# Phase 3 release gate. Supersedes scripts/check_phase2.ps1.
#
# Runs every quality gate the phase is measured by, in the order a failure is
# cheapest to diagnose: contract freshness, tests, lint, types, dataset, then the
# two baselines that must reproduce byte-for-byte.
#
# Per ADR-0003 the Phase 3 baseline reports three evidence metrics side by side.
# Any gate claim must name which one it used.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [string]$Phase0BaselineJson = "docs/evaluation/baseline-phase-0.json",
    [string]$Phase0BaselineMarkdown = "docs/evaluation/baseline-phase-0.md",
    [string]$Phase3BaselineJson = "docs/evaluation/baseline-phase-3.json",
    [string]$Phase3BaselineMarkdown = "docs/evaluation/baseline-phase-3.md"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Output "==> $Label"
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Run scripts/setup_windows.ps1 first."
}

if (-not $SkipSync) {
    Invoke-Checked "Frozen dependency sync" @(
        "sync", "--all-groups", "--frozen"
    )
}

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
    "--json-output", $Phase0BaselineJson,
    "--markdown-output", $Phase0BaselineMarkdown,
    "--check"
)
# The Phase 1 and Phase 2 baselines are historical records of what those engines
# did. They are deliberately not re-checked: the engine has advanced, so demanding
# they reproduce their old numbers would be demanding that Phase 3 changed nothing.

Invoke-Checked "Phase 3 engine baseline" @(
    "run", "python", "scripts/run_phase3_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", $Phase3BaselineJson,
    "--markdown-output", $Phase3BaselineMarkdown,
    "--check"
)

Write-Output "Phase 3 verification completed."

# The verdict belongs in the exit code, not only in the line above it.
# Without this, a caller that reads $LASTEXITCODE after invoking the gate
# gets whatever the last native command left -- measured at 3 through a
# wrapper script. A failing step never reaches here: Invoke-Checked throws
# and $ErrorActionPreference is Stop, which
# tests/unit/test_gate_exit_codes.py pins.
exit 0
