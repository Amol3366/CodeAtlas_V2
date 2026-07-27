# Regenerate (or verify) the web client's API types from the live FastAPI schema.
#
# The types are generated, not hand-written, so a backend change the client has
# not accounted for surfaces as a TypeScript error rather than a runtime
# surprise (ADR-0006 decision 5). `-Check` is the gate form: it fails when the
# checked-in file no longer matches the backend, exactly as the contract schema
# export does.
[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = "Stop"

$web = Join-Path $PSScriptRoot "..\apps\web"
$document = Join-Path $web "openapi.json"
$generated = Join-Path $web "src\lib\api-types.gen.ts"

& uv run python (Join-Path $PSScriptRoot "export_openapi.py") $document
if ($LASTEXITCODE -ne 0) { throw "OpenAPI export failed with exit code $LASTEXITCODE." }

if (-not $Check) {
    Push-Location $web
    try {
        & pnpm exec openapi-typescript openapi.json -o src/lib/api-types.gen.ts
        if ($LASTEXITCODE -ne 0) { throw "Type generation failed with exit code $LASTEXITCODE." }
    } finally { Pop-Location }
    Write-Output "Web API types regenerated."
    exit 0
}

$temporary = Join-Path ([System.IO.Path]::GetTempPath()) "codeatlas-api-types.gen.ts"
Push-Location $web
try {
    & pnpm exec openapi-typescript openapi.json -o $temporary
    if ($LASTEXITCODE -ne 0) { throw "Type generation failed with exit code $LASTEXITCODE." }
} finally { Pop-Location }

$current = (Get-Content $generated -Raw) -replace "`r`n", "`n"
$fresh = (Get-Content $temporary -Raw) -replace "`r`n", "`n"
Remove-Item $temporary -Force

if ($current -ne $fresh) {
    throw "apps/web/src/lib/api-types.gen.ts is stale. Run scripts/generate_web_types.ps1 and review the diff."
}
Write-Output "Web API types are current."
