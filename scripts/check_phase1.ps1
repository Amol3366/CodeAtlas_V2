# SUPERSEDED by scripts/check_phase2.ps1.
#
# Kept as the record of the Phase 1 gate. Its 'Phase 1 engine baseline'
# step no longer passes, and should not: that artifact records what the
# Phase 1 engine did, and the engine has since advanced. Re-running it
# against a later engine exits 5 (stale artifact) by design.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [string]$Phase0BaselineJson = "docs/evaluation/baseline-phase-0.json",
    [string]$Phase0BaselineMarkdown = "docs/evaluation/baseline-phase-0.md",
    [string]$Phase1BaselineJson = "docs/evaluation/baseline-phase-1.json",
    [string]$Phase1BaselineMarkdown = "docs/evaluation/baseline-phase-1.md"
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
Invoke-Checked "Phase 1 engine baseline" @(
    "run", "python", "scripts/run_phase1_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", $Phase1BaselineJson,
    "--markdown-output", $Phase1BaselineMarkdown,
    "--check"
)

Write-Output "Phase 1 verification completed."

# The verdict belongs in the exit code, not only in the line above it.
# Without this, a caller that reads $LASTEXITCODE after invoking the gate
# gets whatever the last native command left -- measured at 3 through a
# wrapper script. A failing step never reaches here: Invoke-Checked throws
# and $ErrorActionPreference is Stop, which
# tests/unit/test_gate_exit_codes.py pins.
exit 0
