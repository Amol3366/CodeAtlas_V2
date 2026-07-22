# Start the CodeAtlas FastAPI dev server (CLAUDE.md §8.4).
# The API app arrives in Phase 7; until then this fails fast with a clear message.

$ErrorActionPreference = "Stop"

if (-not (Test-Path "apps/api/main.py") -or ((Get-Item "apps/api/main.py").Length -eq 0)) {
    Write-Warning "apps/api/main.py is not implemented yet (arrives in Phase 7)."
    exit 0
}

uv run uvicorn apps.api.main:app --reload --port 8000
