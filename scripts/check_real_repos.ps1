# Real-repository validation.
#
# Deliberately NOT part of any gate: it needs the network and takes minutes,
# and a gate that requires the internet is not trustworthy offline. Run it
# before a release, and after any change to parsing, symbol identity, or chunk
# identity.
#
# Every one of the five pinned repositories failed to index before ADR-0069.
# The evaluation corpus could not express that defect, because every fixture is
# a two-file toy -- which is why this script exists beside the corpus rather
# than inside it.
[CmdletBinding()]
param(
    [string]$Only,
    [string]$Workspace
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Run scripts/setup_windows.ps1 first."
}

$arguments = @("run", "python", "scripts/check_real_repos.py")
if ($Only) { $arguments += @("--only", $Only) }
if ($Workspace) { $arguments += @("--workspace", $Workspace) }

& uv @arguments
exit $LASTEXITCODE
