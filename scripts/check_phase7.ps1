# Phase 7 release gate. Supersedes scripts/check_phase6.ps1.
#
# Phase 7 adds an *optional* semantic layer, and that word is the whole reason
# this script is shaped the way it is. The deterministic gate — everything
# inherited from Phase 6 — runs with no provider installed and no provider
# enabled, because gate condition 2 says an installation without the optional
# extras must behave exactly like Phases 0-6. If the semantic work ever made
# the deterministic gate depend on torch, this script would fail to run at all
# on a machine that never opted in, which is precisely the regression the
# condition exists to catch.
#
# The semantic half is therefore opt-in (-Semantic), following the -Package
# precedent from Phase 6: skipped work announces itself and its reason, so a
# run that never exercised the vector store cannot read as one that verified
# it.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [switch]$SkipWeb,
    [switch]$SkipE2E,
    [switch]$Semantic,
    [switch]$Package,
    [switch]$Perf
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

Set-Location $root

if (-not $SkipSync) {
    # Deliberately not `--all-extras`. The default environment is the
    # deterministic one; the semantic extras are installed only by the
    # -Semantic block below, so the checks above it prove what a
    # non-opted-in installation actually does.
    Invoke-Checked "Frozen dependency sync" @("sync", "--all-groups", "--frozen")
}

# --- Backend (deterministic; no provider installed) ----------------------

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

# The Phase 4 baseline is Phase 7's comparison point, not merely an inherited
# check. Gate condition 7 asks for uplift *over the deterministic baseline*,
# and gate condition 5 asks that a provider-disabled run score identically to
# it. Both readings are worthless if the deterministic numbers drifted while
# the semantic layer was being built, so `--check` here is what pins them.
Invoke-Checked "Phase 4 engine baseline (Phase 7 comparison point)" @(
    "run", "python", "scripts/run_phase4_baseline.py",
    "--dataset", "tests/evaluation/cases",
    "--json-output", "docs/evaluation/baseline-phase-4.json",
    "--markdown-output", "docs/evaluation/baseline-phase-4.md",
    "--check"
)

if ($SkipWeb) {
    Write-Output "Phase 7 backend verification completed (web skipped)."
    exit 0
}

# --- Web -----------------------------------------------------------------

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm is required for the web gate. Run scripts/setup_windows.ps1."
}

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

# --- End to end ----------------------------------------------------------

if ($SkipE2E) {
    Write-Output "==> End-to-end suites (skipped by -SkipE2E)"
} else {
    Invoke-Checked "End-to-end suites" @("exec", "playwright", "test") `
        -Command "pnpm" -WorkingDirectory $web
}

# --- Semantic layer (opt-in) ---------------------------------------------

# Installing the local extra pulls sentence-transformers and torch, which is a
# multi-hundred-megabyte download and a slow import. That cost is why this is
# opt-in rather than default, and why it runs after everything cheap has
# already had a chance to fail.
#
# This block grows with the phase. Each task that lands provider, vector-store,
# or generation behavior adds its suite here, and P7-06 adds the uplift
# baseline check that gate condition 7 cites.
if ($Semantic) {
    Invoke-Checked "Semantic extras sync" @(
        "sync", "--all-groups", "--extra", "semantic-local", "--frozen"
    )

    $semanticTests = Join-Path $root "tests\semantic"
    if (Test-Path $semanticTests) {
        Invoke-Checked "Semantic suites" @("run", "pytest", "-q", "tests/semantic")
    } else {
        Write-Output "==> Semantic suites (none yet; P7-02 lands the first)"
    }
} else {
    Write-Output "==> Semantic layer (skipped; pass -Semantic to install the extras and verify)"
}

# --- Packaged build ------------------------------------------------------

if ($Package) {
    Write-Output "==> Packaged build"
    & (Join-Path $PSScriptRoot "build_package.ps1") -SkipWebBuild
    if ($LASTEXITCODE -ne 0) {
        throw "Packaging failed with exit code $LASTEXITCODE."
    }

    Invoke-Checked "Packaged smoke tests" @(
        "run", "pytest", "-q", "tests/end_to_end/test_packaged_build.py"
    )
} else {
    Write-Output "==> Packaged build (skipped; pass -Package to build and verify)"
}

# --- Performance ----------------------------------------------------------

# Still Phase 6's measurement until P7-12 lands `measure_phase7_perf.py`. Gate
# condition 12 asks whether the Section 19.3 targets still hold *with
# embeddings enabled*, which cannot be measured before the embeddings exist —
# so this deliberately keeps measuring the deterministic artifact rather than
# reporting a number that would silently answer a different question.
if ($Perf) {
    Invoke-Checked "Packaged performance (deterministic; Phase 6 measurement)" @(
        "run", "python", "scripts/measure_phase6_perf.py"
    )
} else {
    Write-Output "==> Packaged performance (skipped; pass -Perf to measure)"
}

if ($SkipE2E) {
    Write-Output "Phase 7 verification completed (end-to-end skipped)."
} else {
    Write-Output "Phase 7 verification completed."
}
