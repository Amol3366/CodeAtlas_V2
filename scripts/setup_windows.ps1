[CmdletBinding()]
param(
    [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install uv, then rerun this script."
}

& uv sync --all-groups --frozen
if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed with exit code $LASTEXITCODE."
}

Write-Output "CodeAtlas Python environment is ready."

if ($SkipWeb) {
    Write-Output "Skipping the web application (-SkipWeb)."
    exit 0
}

# Phase 5 adds the web application: Node 20+ and pnpm are prerequisites from
# here on. They are checked rather than installed, because a setup script that
# silently installs a language runtime is doing more than it was asked to.
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 20 or newer is required for apps/web. Install it, then rerun."
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm is required for apps/web. Run 'corepack enable pnpm', then rerun."
}

$web = Join-Path $PSScriptRoot "..pps\web"
Push-Location $web
try {
    & pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm install failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

Write-Output "CodeAtlas web application is ready."
