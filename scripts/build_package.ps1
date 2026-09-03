# Build the packaged Windows release.
#
# PyInstaller in **onedir** form: a folder containing `codeatlas.exe` and its
# dependencies, shipped as a zip. `--onefile` would match ADR-0007's wording
# more literally, but it re-extracts the whole bundle to %TEMP% on every launch
# — seconds of startup for a CLI, and a well-known trigger for Windows
# antivirus heuristics. The user approved onedir on 2026-07-28; the deviation
# and its reasoning are recorded in the ADR-0007 Outcome section.
#
# Four data sets have to be carried explicitly, because none of them is a module:
#
#   * the built web application, so `serve --web` has something to serve;
#   * the SQL migrations, which are read through `importlib.resources` and
#     would otherwise be absent from the frozen build — the failure would not
#     appear until a user's first run against a fresh database;
#   * each query-backed grammar's own `queries/tags.scm` (ADR-0065);
#   * this repository's authored `*.imports.scm`.
#
# The last two were missing on 2026-08-19 and the artifact could not run at all:
# every parser is built eagerly, so `repo add` and `doctor` both died and only
# `--help` worked. `tests/unit/test_gate_script_invocations.py` now derives both
# requirements from the adapters, so a new language fails there in milliseconds
# rather than in a user's first command.
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

# CodeAtlas's own authored import queries (ADR-0065). Read from disk relative to
# `__file__`, so they are data rather than modules and PyInstaller does not find
# them -- the same reason the migrations beside them are carried explicitly.
# Missing, they fail *after* the grammar `tags.scm` files are found, which is how
# the 2026-08-19 rebuild hit two separate data omissions one after the other.
$importQueries = Join-Path $root "src/codeatlas/parsing/query_backed/queries"

# Built from `packaging/codeatlas.spec` since 2026-09-04, because the artifact
# now carries TWO executables -- `codeatlas.exe` and `codeatlas-mcp.exe` -- in
# one shared bundle, and a command-line invocation cannot express that.
# `pyinstaller a.py b.py` builds one program over two scripts, not two
# programs. Only a spec can hand two EXEs to a single COLLECT.
#
# This script still owns WHAT is built; the spec owns only HOW it is assembled.
# The paths below are handed over as environment variables rather than
# recomputed there, so there is exactly one definition of each.
$env:CODEATLAS_BUILD_ROOT = $root
$env:CODEATLAS_BUILD_WEB = $assets
$env:CODEATLAS_BUILD_MIGRATIONS = $migrations
$env:CODEATLAS_BUILD_QUERIES = $importQueries
$env:CODEATLAS_BUILD_SEMANTIC = if ($SemanticLocal) { "1" } else { "0" }

$pyinstallerArgs = @(
    "--noconfirm",
    "--distpath", $dist,
    "--workpath", (Join-Path $dist "build")
)

# The grammar `tags.scm` collection and the -SemanticLocal `collect_all` set
# moved into `packaging/codeatlas.spec` on 2026-09-04, together, when the build
# became spec-driven. They are the same requirements with the same reasons --
# recorded at the top of that file and derived from the adapters by
# `tests/unit/test_gate_script_invocations.py`, which still fails in
# milliseconds if a new language is added without its data.

& uv run pyinstaller @pyinstallerArgs (Join-Path $root "packaging/codeatlas.spec")

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

# The MCP server, verified by speaking the protocol to it.
#
# `--help` cannot check this one: it is a stdio server and would block. More to
# the point, `--help` is exactly what still worked on 2026-08-19 while the rest
# of that artifact was destroyed by two missing data sets, so an existence or
# help check here would repeat a mistake this build script already carries a
# comment about.
#
# `initialize` -> `tools/list` -> one call -> one deliberate failure exercises
# the frozen bundle's data files, the lazily imported `mcp` transport, and the
# error envelope, which is every part of this executable packaging can break.
$mcpExecutable = Join-Path $release "codeatlas-mcp.exe"
if (-not (Test-Path $mcpExecutable)) {
    throw "The build produced no codeatlas-mcp.exe. An agent host has nothing to launch."
}

$mcpProbeDatabase = Join-Path $dist "mcp-verify.sqlite"
if (Test-Path $mcpProbeDatabase) { Remove-Item -Force $mcpProbeDatabase }

& uv run python (Join-Path $root "scripts/verify_mcp_server.py") `
    --db $mcpProbeDatabase --expect-tools 22 -- $mcpExecutable
if ($LASTEXITCODE -ne 0) {
    throw "The packaged MCP server failed verification (exit code $LASTEXITCODE)."
}
Remove-Item -Force $mcpProbeDatabase -ErrorAction SilentlyContinue

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
