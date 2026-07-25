[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install uv, then rerun this script."
}

& uv sync --all-groups --frozen
if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed with exit code $LASTEXITCODE."
}

Write-Output "CodeAtlas Python environment is ready."
