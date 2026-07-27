# Start the local API and the web dev server together.
#
# Two processes because they are two servers: the API on loopback and Vite in
# front of it. Vite proxies `/v1` to the API, so the browser only ever talks to
# one origin and the API keeps its no-CORS, loopback-only posture
# (ADR-0006 decision 9).
[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [switch]$ApiOnly
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Run scripts/setup_windows.ps1 first."
}

$root = Split-Path -Parent $PSScriptRoot
$api = Start-Process -PassThru -NoNewWindow -FilePath "uv" -ArgumentList @(
    "run", "uvicorn", "codeatlas.api.app:create_app", "--factory",
    "--host", "127.0.0.1", "--port", "$ApiPort"
) -WorkingDirectory $root

Write-Output "API starting on http://127.0.0.1:$ApiPort (pid $($api.Id))."

if ($ApiOnly) {
    Wait-Process -Id $api.Id
    exit 0
}

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $api.Id -Force
    throw "pnpm is required for the web dev server. Run scripts/setup_windows.ps1."
}

$web = Join-Path $root "apps\web"
if (-not (Test-Path (Join-Path $web "node_modules"))) {
    Stop-Process -Id $api.Id -Force
    throw "apps/web dependencies are missing. Run scripts/setup_windows.ps1."
}

Push-Location $web
try {
    & pnpm dev
} finally {
    Pop-Location
    # The API was started by this script, so this script stops it. Leaving a
    # stray server bound to the port would make the next run fail confusingly.
    if (-not $api.HasExited) {
        Stop-Process -Id $api.Id -Force
    }
}
