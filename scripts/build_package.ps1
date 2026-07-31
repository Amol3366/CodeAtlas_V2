# Build the packaged Windows release.
#
# PyInstaller in **onedir** form: a folder containing `codeatlas.exe` and its
# dependencies, shipped as a zip. `--onefile` would match ADR-0007's wording
# more literally, but it re-extracts the whole bundle to %TEMP% on every launch
# — seconds of startup for a CLI, and a well-known trigger for Windows
# antivirus heuristics. The user approved onedir on 2026-07-28; the deviation
# and its reasoning are recorded in the ADR-0007 Outcome section.
#
# Two data sets have to be carried explicitly, because neither is a module:
#
#   * the built web application, so `serve --web` has something to serve;
#   * the SQL migrations, which are read through `importlib.resources` and
#     would otherwise be absent from the frozen build — the failure would not
#     appear until a user's first run against a fresh database.
[CmdletBinding()]
param(
    [switch]$SkipWebBuild,
    [switch]$SkipZip,
    [switch]$SemanticLocal
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps/web"
$dist = Join-Path $root "dist"
$staging = Join-Path $dist "codeatlas"
$release = Join-Path $dist "codeatlas-win64"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Run scripts/setup_windows.ps1 first."
}

# --- The web application --------------------------------------------------

if (-not $SkipWebBuild) {
    Write-Output "==> Building the web application"
    & pnpm --dir $web exec vite build
    if ($LASTEXITCODE -ne 0) {
        throw "The web build failed with exit code $LASTEXITCODE."
    }
}

$assets = Join-Path $web "dist"
if (-not (Test-Path (Join-Path $assets "index.html"))) {
    throw "apps/web/dist/index.html is missing. Build the web application first."
}

# --- The executable -------------------------------------------------------

Write-Output "==> Building the executable"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
if (Test-Path $release) { Remove-Item -Recurse -Force $release }

$migrations = Join-Path $root "src/codeatlas/storage/sqlite/migrations"

$pyinstallerArgs = @(
    "--noconfirm",
    "--name", "codeatlas",
    "--distpath", $dist,
    "--workpath", (Join-Path $dist "build"),
    "--specpath", (Join-Path $dist "spec"),
    "--add-data", "$assets;web",
    "--add-data", "$migrations;codeatlas/storage/sqlite/migrations",
    "--collect-submodules", "uvicorn"
)

if ($SemanticLocal) {
    Write-Output "==> Including semantic-local optional dependencies"
    $pyinstallerArgs += @(
        "--collect-all", "huggingface_hub",
        "--collect-all", "lancedb",
        "--collect-all", "pyarrow",
        "--collect-all", "safetensors",
        "--collect-all", "sentence_transformers",
        "--collect-all", "sklearn",
        "--collect-all", "tokenizers",
        "--collect-all", "torch",
        "--collect-all", "transformers"
    )
}

& uv run pyinstaller @pyinstallerArgs (Join-Path $root "packaging/entry.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Move-Item -Path $staging -Destination $release

# --- Verify before calling it a release -----------------------------------

Write-Output "==> Verifying the artifact"
$executable = Join-Path $release "codeatlas.exe"
if (-not (Test-Path $executable)) {
    throw "The build produced no codeatlas.exe."
}

# A build that cannot answer `--help` is not a build. Catching it here beats
# discovering it in the smoke tests, which take longer to reach.
& $executable --help > $null
if ($LASTEXITCODE -ne 0) {
    throw "The packaged executable failed to run (exit code $LASTEXITCODE)."
}

if (-not $SkipZip) {
    Write-Output "==> Zipping"
    $archive = Join-Path $dist "codeatlas-win64.zip"
    if (Test-Path $archive) { Remove-Item -Force $archive }

    # Retried because the handle on a freshly written .exe outlives the process
    # that ran it: Windows Defender scans new executables, and the verification
    # run above is exactly what triggers that scan. Failing here would report a
    # good build as a broken one.
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            Compress-Archive -Path $release -DestinationPath $archive -ErrorAction Stop
            break
        } catch {
            if ($attempt -ge 5) { throw }
            Write-Output "    zip attempt $attempt failed; retrying"
            Start-Sleep -Seconds 2
        }
    }
    Write-Output "Packaged: $archive"
}

Write-Output "Packaged: $release"
