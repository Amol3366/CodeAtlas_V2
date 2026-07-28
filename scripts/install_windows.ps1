# Install a packaged CodeAtlas build for the current user.
#
# Optional: the unzipped folder works as-is from anywhere. This exists so that
# `codeatlas` is on PATH, which is how every documented command in this
# repository is written.
#
# **No elevation, and no machine-wide state.** It copies the build into
# %LOCALAPPDATA% and appends that folder to the *user* PATH. Those are the only
# two things it changes, and `-Uninstall` reverses exactly those two — an
# installer that cannot be undone precisely is one users are right to distrust
# (ADR-0007 decision 6).
[CmdletBinding()]
param(
    [string]$Source,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$target = Join-Path $env:LOCALAPPDATA "CodeAtlas\app"

function Get-UserPath {
    $value = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($null -eq $value) { return @() }
    return $value.Split(';') | Where-Object { $_ -ne "" }
}

function Set-UserPath([string[]]$entries) {
    [Environment]::SetEnvironmentVariable("Path", ($entries -join ';'), "User")
}

if ($Uninstall) {
    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
        Write-Output "Removed $target."
    } else {
        Write-Output "Nothing installed at $target."
    }

    $remaining = Get-UserPath | Where-Object { $_ -ne $target }
    Set-UserPath $remaining
    Write-Output "Removed $target from the user PATH."
    Write-Output ""
    Write-Output "Your data was NOT removed. It lives in:"
    Write-Output "  $(Join-Path $env:LOCALAPPDATA 'CodeAtlas\data')"
    Write-Output "Delete that folder too if you want CodeAtlas gone entirely."
    exit 0
}

# --- Install --------------------------------------------------------------

if (-not $Source) {
    $Source = Join-Path (Split-Path -Parent $PSScriptRoot) "dist/codeatlas-win64"
}

if (-not (Test-Path (Join-Path $Source "codeatlas.exe"))) {
    throw "No codeatlas.exe under '$Source'. Pass -Source <unzipped folder>."
}

if (Test-Path $target) {
    # Replacing rather than merging: a leftover file from an older build is the
    # kind of thing that produces an impossible bug report.
    Remove-Item -Recurse -Force $target
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $target -Recurse -Force
Write-Output "Installed to $target."

$entries = Get-UserPath
if ($entries -notcontains $target) {
    Set-UserPath ($entries + $target)
    Write-Output "Added $target to the user PATH."
    Write-Output "Open a new terminal for it to take effect."
} else {
    Write-Output "$target is already on the user PATH."
}

Write-Output ""
Write-Output "Try:"
Write-Output "  codeatlas doctor"
Write-Output "  codeatlas serve --web --open"
