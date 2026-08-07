# Phase 4 release gate. Supersedes scripts/check_phase3.ps1.
#
# Runs every quality gate the phase is measured by, in the order a failure is
# cheapest to diagnose: contract freshness, tests, lint, types, dataset, then
# the baselines that must reproduce byte-for-byte. The Phase 4 baseline now
# carries real change metrics; per ADR-0003 any gate claim names which
# evidence metric it used, and `exact_evidence_rate` is reported beside
# `containing_evidence_rate`.
#
# Performance is measured separately by scripts/measure_phase4_perf.py and
# recorded with hardware in docs/evaluation/phase-4-baseline-environment.md;
# a wall-clock benchmark inside a correctness gate would make the gate flaky.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [string]$Phase0BaselineJson = "docs/evaluation/baseline-phase-0.json",
    [string]$Phase0BaselineMarkdown = "docs/evaluation/baseline-phase-0.md",
    [string]$Phase3BaselineJson = "docs/evaluation/baseline-phase-3.json",
    [string]$Phase3BaselineMarkdown = "docs/evaluation/baseline-phase-3.md",
    [string]$Phase4BaselineJson = "docs/evaluation/baseline-phase-4.json",
    [string]$Phase4BaselineMarkdown = "docs/evaluation/baseline-phase-4.md",
    [string]$InvariantsJson = "docs/evaluation/invariants.json",
    [string]$InvariantsMarkdown = "docs/evaluation/invariants.md"
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
# The Phase 1 and Phase 2 baselines are historical records of what those
# engines did and are deliberately not re-checked. The Phase 3 baseline is
# still re-checked because it pins the query-side engine Phase 4 did not
# change; if it moves, something moved that Phase 4 had no business moving.
Invoke-Checked "Phase 3 engine baseline" @(
    "run", "python", "scripts/run_phase3_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", $Phase3BaselineJson,
    "--markdown-output", $Phase3BaselineMarkdown,
    "--check"
)
Invoke-Checked "Phase 4 engine baseline" @(
    "run", "python", "scripts/run_phase4_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", $Phase4BaselineJson,
    "--markdown-output", $Phase4BaselineMarkdown,
    "--check"
)

# The Phase 4 corpus measures accuracy across 24 representative cases. It has
# no fixture- or helper-mediated scenario, so it cannot see the ADR-0016
# invariant at all. This step is the one that can.
Invoke-Checked "ADR-0016 invariants" @(
    "run", "python", "scripts/check_invariants.py",
    "--corpus", "tests/evaluation/invariant_cases",
    "--json-output", $InvariantsJson,
    "--markdown-output", $InvariantsMarkdown,
    "--check"
)

Write-Output "Phase 4 verification completed."
