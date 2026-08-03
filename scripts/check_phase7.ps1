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
Invoke-Checked "Phase 7 rerank A/B artifact" @(
    "run", "python", "scripts/run_phase7_rerank_ab.py",
    "--semantic-baseline", "docs/evaluation/baseline-phase-7.json",
    "--json-output", "docs/evaluation/rerank-phase-7.json",
    "--markdown-output", "docs/evaluation/rerank-phase-7.md",
    "--check"
)
# The explanation A/B is deliberately NOT a gate step.
#
# It was one until `2d7e511` rewrote it to be a real measurement: it now answers
# the evaluation corpus twice through the same services, differing only in
# whether an Ollama provider is attached. That needs a live `llama3.2:3b`, and
# `--check` does not avoid it — the script measures first and compares
# afterwards, so every invocation needs the model.
#
# Running it here would make an optional provider a hard requirement of the
# quality gate, which Section 4.3 forbids: no deterministic capability may
# depend on a provider being present. The artifact stays a recorded manual
# measurement, named with the model that produced it, exactly as ADR-0012
# describes.
#
# To refresh it, with Ollama running:
#
#   uv run python scripts/run_phase7_explanation_ab.py `
#       --dataset tests/evaluation/cases `
#       --json-output docs/evaluation/explanation-phase-7.json `
#       --markdown-output docs/evaluation/explanation-phase-7.md
#
# The rewrite left this call site passing the old `--semantic-baseline`, so the
# gate threw here on every run from `2d7e511` until this was removed.

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

    # Gate condition 7. Both sides of this comparison run here rather than
    # above, because running the deterministic side in a different environment
    # from the semantic side would compare two things differing in more than
    # the switch under test.
    #
    # `--check` pins the measurement the same way the Phase 3 and 4 baselines
    # are pinned: the artifact is committed, and a run that no longer
    # reproduces it is a change to the answer that has to be reviewed rather
    # than absorbed. The real model's embeddings reproduce byte-for-byte on
    # CPU, which is what makes that possible.
    Invoke-Checked "Phase 7 semantic uplift baseline" @(
        "run", "python", "scripts/run_phase7_baseline.py",
        "--dataset", "tests/evaluation/semantic_cases",
        "--json-output", "docs/evaluation/baseline-phase-7.json",
        "--markdown-output", "docs/evaluation/baseline-phase-7.md",
        "--check"
    )
} else {
    Write-Output "==> Semantic layer (skipped; pass -Semantic to install the extras and verify)"
}

# --- Packaged build ------------------------------------------------------

if ($Package) {
    Write-Output "==> Packaged build"
    $packageArgs = @("-SkipWebBuild")
    if ($Semantic) {
        $packageArgs += "-SemanticLocal"
        $packageArgs += "-SkipZip"
    }
    & (Join-Path $PSScriptRoot "build_package.ps1") @packageArgs
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

# Gate condition 12 asks for the packaged artifact with embeddings enabled.
# The script refuses to substitute a deterministic-only number when the local
# model or the semantic package build is missing.
if ($Perf) {
    Invoke-Checked "Packaged performance with local embeddings enabled" @(
        "run", "python", "scripts/measure_phase7_perf.py",
        "--json-output", "docs/evaluation/baseline-phase-7-perf.json"
    )
} else {
    Write-Output "==> Packaged performance (skipped; pass -Perf to measure)"
}

if ($SkipE2E) {
    Write-Output "Phase 7 verification completed (end-to-end skipped)."
} else {
    Write-Output "Phase 7 verification completed."
}
