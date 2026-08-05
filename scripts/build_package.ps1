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

# --- Staleness guard -------------------------------------------------------
#
# `-SkipWebBuild` reuses whatever is in `apps/web/dist`, which is what the
# quality gate wants: it has just built the web application itself, and
# rebuilding costs seconds for no gain. The hazard is the same switch used
# against an old `dist` — the package then ships an interface the source tree
# no longer has, and nothing says so.
#
# That is not hypothetical. On 2026-08-05 a package built four days before a
# Settings redesign served the pre-redesign page, and the mismatch was invisible
# from outside: a stale package and a stale browser cache look identical, so
# three rounds of debugging went after the cache. Running the source checkout to
# check kept confirming the *other* bundle, because the server picks its assets
# by launch mode.
#
# Compared against the newest web source rather than a fixed age, so the check
# stays true whenever it runs. `node_modules` is excluded: it moves on install
# and says nothing about the UI.
if ($SkipWebBuild) {
    $builtAt = (Get-Item (Join-Path $assets "index.html")).LastWriteTimeUtc

    $sourcePaths = @("src", "index.html", "package.json", "vite.config.ts", "tsconfig.json") |
        ForEach-Object { Join-Path $web $_ } |
        Where-Object { Test-Path $_ }

    $newest = Get-ChildItem -Path $sourcePaths -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if ($newest -and $newest.LastWriteTimeUtc -gt $builtAt) {
        $relative = $newest.FullName.Substring($root.Length).TrimStart('\', '/')
        throw @"
apps/web/dist is older than the web application source, so -SkipWebBuild would
package an interface that no longer exists.

  newest source : $relative ($($newest.LastWriteTimeUtc.ToString('u')))
  apps/web/dist : $($builtAt.ToString('u'))

Run without -SkipWebBuild, or build it yourself with `pnpm --dir apps/web build`.
"@
    }
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

# What shipped must be what was built. The guard above stops a stale `dist`
# reaching PyInstaller; this stops PyInstaller carrying something else — a
# `--add-data` pointed at the wrong place, or a partial copy. Checked in both
# known locations because onedir builds nest data under `_internal` in current
# PyInstaller and placed it beside the executable in older ones.
$bundledWeb = @(
    (Join-Path $release "_internal/web"),
    (Join-Path $release "web")
) | Where-Object { Test-Path (Join-Path $_ "index.html") } | Select-Object -First 1

if (-not $bundledWeb) {
    throw "The packaged build carries no web assets. `serve --web` would refuse."
}

function Get-TreeDigest([string]$directory) {
    Get-ChildItem -Path $directory -Recurse -File |
        Sort-Object { $_.FullName.Substring($directory.Length) } |
        ForEach-Object {
            $name = $_.FullName.Substring($directory.Length).TrimStart('\', '/').Replace('\', '/')
            "$name=$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)"
        }
}

$bundledDigest = (Get-TreeDigest $bundledWeb) -join "`n"
$sourceDigest = (Get-TreeDigest $assets) -join "`n"

if ($bundledDigest -ne $sourceDigest) {
    throw @"
The packaged web assets differ from apps/web/dist. The build would ship a
different interface from the one just built, which is the failure this check
exists to prevent. Inspect $bundledWeb against $assets.
"@
}

Write-Output "    web assets match apps/web/dist"

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
