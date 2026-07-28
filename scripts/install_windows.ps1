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

$upgrading = Test-Path (Join-Path $target "codeatlas.exe")

if (Test-Path $target) {
    # Refuse rather than delete out from under a running process. Removing the
    # folder while codeatlas.exe is running fails partway through and leaves a
    # half-replaced install, which is worse than the old one it was fixing.
    $running = Get-Process -Name "codeatlas" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($target, [StringComparison]::OrdinalIgnoreCase) }
    if ($running) {
        throw "CodeAtlas is running from '$target' (pid $($running.Id -join ', ')). Stop it and run this again."
    }

    # Replacing rather than merging: a leftover file from an older build is the
    # kind of thing that produces an impossible bug report.
    Remove-Item -Recurse -Force $target
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $target -Recurse -Force
if ($upgrading) {
    Write-Output "Upgraded the build in $target."
} else {
    Write-Output "Installed to $target."
}

# The app folder is replaceable; the data folder is not, and the two are
# deliberately separate. Say what happens to the database rather than leaving a
# user to wonder whether an upgrade just ate their history.
$database = Join-Path $env:LOCALAPPDATA "CodeAtlas\data\codeatlas.db"
if (Test-Path $database) {
    Write-Output ""
    Write-Output "Your existing database was left untouched:"
    Write-Output "  $database"
    Write-Output "It is upgraded on first run, after a checkpoint is written beside it."
    Write-Output "Run 'codeatlas upgrade' first if you would rather watch it happen."
}

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
