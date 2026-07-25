[CmdletBinding()]
param(
    [switch]$SkipSync,
    [string]$BaselineJson = "docs/evaluation/baseline-phase-0.json",
    [string]$BaselineMarkdown = "docs/evaluation/baseline-phase-0.md"
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
Invoke-Checked "Lint" @("run", "ruff", "check", "src", "tests", "scripts")
Invoke-Checked "Types" @(
    "run", "mypy", "--no-incremental", "src", "tests", "scripts"
)
Invoke-Checked "Dataset validation" @(
    "run", "python", "scripts/run_evaluation.py", "validate",
    "--dataset", "tests/evaluation/cases"
)
Invoke-Checked "Null baseline" @(
    "run", "python", "scripts/run_evaluation.py", "null-baseline",
    "--dataset", "tests/evaluation/cases",
    "--json-output", $BaselineJson,
    "--markdown-output", $BaselineMarkdown,
    "--check"
)

Write-Output "Phase 0 verification completed."
