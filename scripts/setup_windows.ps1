# Reproduces CodeAtlas environment setup on a fresh Windows 11 machine.
# Mirrors CLAUDE.md §8.1-8.2. Run from the repository root in PowerShell 7+.
# Optional admin steps (long paths) are attempted and skipped gracefully if not elevated.

$ErrorActionPreference = "Stop"

Write-Host "== CodeAtlas Windows setup ==" -ForegroundColor Cyan

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# --- §8.1 Prerequisites -----------------------------------------------------
if (-not (Test-Command "git"))    { winget install --id Git.Git -e --source winget }
if (-not (Test-Command "python")) { winget install --id Python.Python.3.12 -e --source winget }
if (-not (Test-Command "uv"))     { powershell -c "irm https://astral.sh/uv/install.ps1 | iex" }

git --version
uv --version

# --- Long paths (best-effort; requires admin for the registry key) ----------
try {
    New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
        -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force | Out-Null
    Write-Host "LongPathsEnabled set." -ForegroundColor Green
} catch {
    Write-Warning "Could not set LongPathsEnabled (run as admin to enable)."
}
git config --global core.longpaths true

# --- §8.2 Project environment ----------------------------------------------
uv venv --python 3.12
uv sync --all-extras --group dev

# --- Verify -----------------------------------------------------------------
uv run python -c "import fastapi, sqlalchemy, tree_sitter, watchdog, rapidfuzz, git, structlog, orjson, typer; print('core OK')"
uv run python -c "import tree_sitter_python, tree_sitter_javascript, tree_sitter_typescript; print('parsers OK')"
uv run pytest --version
uv run ruff --version
uv run mypy --version

Write-Host "== Setup complete ==" -ForegroundColor Cyan
