# SUPERSEDED by scripts/check_phase3.ps1.
#
# Kept as the record of the Phase 2 gate. Two of its steps no longer pass, and
# should not:
#
#   'Phase 2 engine baseline' — that artifact records what the Phase 2 engine
#   did. ADR-0003 added exact_evidence_rate and containing_evidence_rate, which
#   changes the artifact *schema*, and PARSER_BUNDLE_VERSION 1.1.0 changes every
#   snapshot ID. Re-running it against a later engine exits 5 (stale artifact)
#   by design. The Phase 2 artifacts are kept unchanged and are NOT regenerated.
#
#   'Phase 0 null baseline' — still checked, and still passes. That artifact was
#   regenerated in P3-SETUP to carry the two new metric fields, both null. No
#   recorded value changed; only the schema did.
#
# Previously: Phase 2 release gate, superseding scripts/check_phase1.ps1.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [string]$Phase0BaselineJson = "docs/evaluation/baseline-phase-0.json",
    [string]$Phase0BaselineMarkdown = "docs/evaluation/baseline-phase-0.md",
    [string]$Phase2BaselineJson = "docs/evaluation/baseline-phase-2.json",
    [string]$Phase2BaselineMarkdown = "docs/evaluation/baseline-phase-2.md"
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
# The Phase 1 baseline is a historical record of what the Phase 1 engine did.
# It is deliberately not re-checked here: the engine has advanced, so demanding
# it reproduce Phase 1 numbers would be demanding that Phase 2 changed nothing.

Invoke-Checked "Phase 2 engine baseline" @(
    "run", "python", "scripts/run_phase2_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", $Phase2BaselineJson,
    "--markdown-output", $Phase2BaselineMarkdown,
    "--check"
)

Write-Output "Phase 2 verification completed."

# The verdict belongs in the exit code, not only in the line above it.
# Without this, a caller that reads $LASTEXITCODE after invoking the gate
# gets whatever the last native command left -- measured at 3 through a
# wrapper script. A failing step never reaches here: Invoke-Checked throws
# and $ErrorActionPreference is Stop, which
# tests/unit/test_gate_exit_codes.py pins.
exit 0
