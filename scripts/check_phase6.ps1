# Phase 6 release gate. Supersedes scripts/check_phase5.ps1.
#
# Same two halves as Phase 5 — backend first, then generated types, then the
# web application — plus the end-to-end suites Phase 6 exists to add.
#
# Playwright runs here rather than separately, because closing the Phase 5
# coverage debt means the browser suites must be part of what 'the gate
# passed' asserts. It is opt-out (-SkipE2E) for a fast inner loop, and it is
# last because it is the slowest and the most environment-dependent.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [switch]$SkipWeb,
    [switch]$SkipE2E,
    [switch]$Package,
    [switch]$Perf
)

$ErrorActionPreference = "Stop"

# -SkipWeb does not skip a section. It *stops the script* -- "backend checks
# only, then stop" -- and the -Package and -Perf blocks sit below that exit, so
# combining them discarded the work those flags asked for while still exiting
# 0. Found in check_phase7.ps1 on 2026-08-10 and present here for the same
# reason; the Phase 6 gate evidence is unaffected, because it was recorded from
# `-Package -Perf` without -SkipWeb.
#
# Checked before any work, so a releaser is told in a second rather than after
# the suite. Guarded by tests/unit/test_gate_flag_combinations.py.
if ($SkipWeb -and ($Package -or $Perf)) {
    throw "-SkipWeb stops after the backend checks, so it cannot be combined with -Package or -Perf: that work comes later and would be skipped silently. Drop -SkipWeb, or drop the flag whose work you do not need."
}

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
    Write-Output "Phase 6 backend verification completed (web skipped)."
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

# --- End to end ----------------------------------------------------------

# `-SkipE2E` skips Playwright and nothing else. It used to return here, which
# meant `-SkipE2E -Package` reported success having never built the artifact —
# the precise failure the packaging block below exists to avoid.
if ($SkipE2E) {
    Write-Output "==> End-to-end suites (skipped by -SkipE2E)"
} else {
    Invoke-Checked "End-to-end suites" @("exec", "playwright", "test") `
        -Command "pnpm" -WorkingDirectory $web
}

# --- Packaged build ------------------------------------------------------

# Opt-in: PyInstaller takes minutes, and most runs of this gate change one
# Python file. Without -Package the packaged smoke tests skip *with their
# reason stated*, so a gate that never built the artifact does not read as one
# that verified it. P6-07 and P6-08 both require the packaged form, which is
# what keeps packaging from rotting unnoticed.
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

# Opt-in, and it measures the *artifact*: gate condition 7 asks for the Section
# 19.3 targets on the packaged build. The committed record of a measurement is
# `docs/evaluation/baseline-phase-6.{json}` plus the named hardware in
# `phase-6-baseline-environment.md`, which is what the gate cites — this switch
# is how that record is refreshed and re-checked.
if ($Perf) {
    Invoke-Checked "Packaged performance" @(
        # The default 20 samples, which is what Phase 4 used and what the
        # committed baseline records. It was pinned to 10 while the access-log
        # hang capped a run; measuring at a different count than the baseline
        # would compare two different things.
        "run", "python", "scripts/measure_phase6_perf.py"
    )
} else {
    Write-Output "==> Packaged performance (skipped; pass -Perf to measure)"
}

if ($SkipE2E) {
    Write-Output "Phase 6 verification completed (end-to-end skipped)."
} else {
    Write-Output "Phase 6 verification completed."
}

# The verdict belongs in the exit code, not only in the line above it.
# Without this, a caller that reads $LASTEXITCODE after invoking the gate
# gets whatever the last native command left -- measured at 3 through a
# wrapper script. A failing step never reaches here: Invoke-Checked throws
# and $ErrorActionPreference is Stop, which
# tests/unit/test_gate_exit_codes.py pins.
exit 0
